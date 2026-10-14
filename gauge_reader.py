"""命令行入口：单张识别、文件夹批处理。运行 --help 查看参数。"""
import argparse
import csv
import json
import math
from collections import Counter
from dataclasses import replace
from pathlib import Path

import cv2

from core import OUTPUT_FILES, Calibration, Params, analyze, write_json

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def matching_file(image, folder, stem_counts, suffix=".json"):
    """优先匹配含图片后缀的名称；同 stem 多图片时禁止共用简写。"""
    # a.png.json 比 a.json 更明确；存在 a.png、a.jpg 时必须分别标定。
    exact = folder / (image.name + suffix)
    if exact.is_file():
        return exact
    short = folder / (image.stem + suffix)
    if short.is_file():
        if stem_counts[image.stem.casefold()] > 1:
            raise ValueError(f"同名不同后缀图片匹配不明确，请使用 {exact.name}")
        return short
    return None


def batch_read(folder, calibration, out_dir, params=None, references=None,
               use_auto_circle=False, *, calibration_dir=None):
    """使用共用标定，或按文件名加载逐图标定；单图失败不会中断批次。"""
    folder, out = Path(folder), Path(out_dir)
    if not folder.is_dir():
        raise ValueError("输入文件夹不存在")
    paths = sorted(x for x in folder.iterdir() if x.is_file() and x.suffix.lower() in IMAGE_SUFFIXES)
    if not paths:
        raise ValueError("输入文件夹内没有支持的图片（只扫描当前层）")
    # 两种标定来源互斥：同为 None 或同不为 None 都不满足“恰选一种”。
    if (calibration is None) == (calibration_dir is None):
        raise ValueError("必须且只能选择共用标定或逐图标定文件夹")
    if calibration_dir is not None:
        calibration_dir = Path(calibration_dir)
        if not calibration_dir.is_dir():
            raise ValueError("标定文件夹不存在")
    else:
        calibration.validate()
    # 批次目录不能是输入/标定目录或其祖先，否则子目录和汇总文件可能破坏源数据。
    protected = [folder] + ([calibration_dir] if calibration_dir is not None else [])
    for source_dir in protected:
        if out.resolve() == source_dir.resolve() or out.resolve() in source_dir.resolve().parents:
            raise ValueError("批量输出目录不能是输入或标定目录及其祖先，请选择独立的结果目录")
    params = params or Params()
    params.validate()
    stem_counts = Counter(path.stem.casefold() for path in paths)
    refs = {}
    # CSV 按完整图片名关联；空参考值跳过，数值 0 则是有效参考读数。
    if references:
        with Path(references).open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not {"filename", "manual_value"}.issubset(reader.fieldnames or []):
                raise ValueError("人工读数 CSV 必须包含 filename 和 manual_value 列")
            for row in reader:
                if row.get("manual_value") is None or not (row.get("filename") or "").strip():
                    raise ValueError("人工读数 CSV 存在缺少文件名或字段的行")
                if row["manual_value"].strip():
                    if row["filename"] in refs:
                        raise ValueError("人工读数 CSV 中存在重复 filename")
                    value = float(row["manual_value"])
                    if not math.isfinite(value):
                        raise ValueError("人工读数 CSV 中的参考值必须为有限数值")
                    refs[row["filename"]] = value
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for path in paths:
        dest = out / path.name  # 保留后缀，避免同名 jpg/png 的输出相互覆盖
        cal_file = params_file = None
        try:
            # 标定加载也可能失败；先移除上次成功图，避免将旧图误认为本次结果。
            for stale in OUTPUT_FILES:
                (dest / stale).unlink(missing_ok=True)
            cal, image_params = calibration, params
            if calibration_dir is not None:
                cal_file = matching_file(path, calibration_dir, stem_counts)
                if cal_file is None:
                    raise ValueError(f"缺少标定文件：{path.stem}.json（或 {path.name}.json）")
                cal = Calibration.load(cal_file)
                params_file = matching_file(path, calibration_dir, stem_counts, ".params.json")
                if params_file is not None:
                    # 逐图参数只覆盖指定字段，其余沿用公共参数，且不修改原对象。
                    overrides = json.loads(params_file.read_text(encoding="utf-8-sig"))
                    image_params = replace(params, **overrides)
                    image_params.validate()
            r = analyze(path, cal, dest, image_params, refs.get(path.name), use_auto_circle)
        except (OSError, ValueError, RuntimeError, TypeError, cv2.error) as exc:
            # 将预期的数据/图像异常转为单张失败记录，让后续图片继续执行。
            r = {"image": str(path), "status": "failed", "error": str(exc)}
        r["filename"] = path.name
        # 标定/图像读取等可能在 analyze 返回前失败，也要保留 CSV 的参考值（含 0）。
        if path.name in refs:
            r["manual_value"] = refs[path.name]
        if calibration_dir is not None:
            r["calibration_file"] = str(cal_file) if cal_file else None
            r["params_file"] = str(params_file) if params_file else None
        try:
            write_json(dest / "result.json", r)
        except OSError as exc:
            # 单张目录冲突或权限错误不应阻断整批；错误至少保存在根目录汇总中。
            r["status"] = "failed"
            r["write_error"] = str(exc)
            message = f"结果文件写入失败：{exc}"
            r["error"] = f"{r['error']}; {message}" if r.get("error") else message
        results.append(r)
    # 汇总包含失败行，防止只报告输出读数的图片而掩盖拒识数量。
    fields = ["filename", "calibration_file", "params_file", "status", "reading", "unit", "angle_deg", "ray_support", "manual_value",
              "signed_error", "absolute_error", "relative_error_pct", "full_scale_error_pct", "error", "write_error"]
    with (out / "summary.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    write_json(out / "summary.json", results)
    return results


def main():
    # CLI 只负责参数解析和调度；实际单图算法集中在 core.analyze。
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("read", "batch"):
        p = sub.add_parser(name)
        p.add_argument("input", help="图片路径或文件夹路径")
        calibration_args = p.add_mutually_exclusive_group(required=True)
        calibration_args.add_argument("--calibration", help="共用标定 JSON，不自动猜测量程")
        if name == "batch":
            calibration_args.add_argument("--calibration-dir", help="逐图标定目录：图片名.json，可含 图片名.params.json")
        p.add_argument("--out", default="outputs")
        p.add_argument("--params", help="参数 JSON，只填要覆盖的字段")
        p.add_argument("--auto-circle", action="store_true")
        if name == "read":
            p.add_argument("--manual-value", type=float)
        else:
            p.add_argument("--references", help="人工读数 CSV: filename,manual_value")
    args = parser.parse_args()
    try:
        cal = Calibration.load(args.calibration) if args.calibration else None
        params = Params(**json.loads(Path(args.params).read_text(encoding="utf-8"))) if args.params else Params()
        params.validate()
        if args.command == "read":
            result = analyze(args.input, cal, args.out, params, args.manual_value, args.auto_circle)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "ok" else 2
        results = batch_read(args.input, cal, args.out, params, args.references, args.auto_circle,
                             calibration_dir=args.calibration_dir)
        ok = sum(x["status"] == "ok" for x in results)
        print(f"完成 {len(results)} 张，成功 {ok} 张，失败 {len(results)-ok} 张。输出: {args.out}")
        # 退出码 2 表示批次有失败，并不表示已完成的结果没有保存。
        return 0 if ok == len(results) else 2
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        parser.exit(2, f"错误: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
