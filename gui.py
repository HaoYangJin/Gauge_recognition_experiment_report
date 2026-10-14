"""Tkinter 桌面界面：图片选择、四点标定、单张识别、批处理。

运行 python gui.py。计算线程只写队列，所有 Tk 操作都在主线程。
"""
import math
import queue
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import cv2
from PIL import Image, ImageTk

from core import Calibration, Params, analyze, angle_at, read_image
from gauge_reader import batch_read


class GaugeApp:
    def __init__(self, root):
        self.root = root
        families = {name.lower(): name for name in tkfont.families(root)}
        self.font_family = next((families[name.lower()] for name in ("Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "WenQuanYi Bitmap Song") if name.lower() in families), "sans-serif")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont"):
            tkfont.nametofont(name).configure(family=self.font_family, size=10)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=(self.font_family, 10))
        self.root.title("指针仪表读数实验")
        self.root.geometry("1160x830")
        self.root.minsize(980, 780)
        self.path = None
        self.image = None
        self.shown = None
        self.photo = None
        self.cal = None
        self.clicks = []
        self.calibrating = False
        self.busy = False
        # 后台线程通过队列交回结果，避免直接操作只能由主线程更新的 Tk 控件。
        self.events = queue.Queue()
        self.fields = {}
        self.status = tk.StringVar(value="先选择照片，再四点标定或载入标定文件。")
        self.result_text = tk.StringVar(value="尚未识别")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(root, background="#e9edf1", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<Button-1>", self.on_click)
        panel = ttk.Frame(root, padding=(6, 14, 16, 12))
        panel.grid(row=0, column=1, sticky="ns")
        ttk.Label(panel, text="指针仪表读数", font=(self.font_family, 17, "bold")).pack(anchor="w", pady=(0, 12))
        self.buttons = []
        def button(text, cmd):
            b = ttk.Button(panel, text=text, command=cmd)
            b.pack(fill="x", pady=3)
            self.buttons.append(b)
        button("1  选择仪表照片", self.open_image)
        button("2  四点标定", self.start_calibration)
        button("载入标定 JSON", self.load_calibration)
        button("保存当前标定", self.save_calibration)
        form = ttk.Frame(panel)
        form.pack(fill="x", pady=12)
        for i, (key, title, default) in enumerate([
            ("min_value", "最小刻度", "0"), ("max_value", "最大刻度", "1.6"),
            ("unit", "单位", "MPa"), ("manual_value", "人工读数 可空", "")]):
            ttk.Label(form, text=title).grid(row=i, column=0, sticky="w", pady=4)
            v = tk.StringVar(value=default)
            self.fields[key] = v
            ttk.Entry(form, textvariable=v, width=16).grid(row=i, column=1, sticky="ew", padx=(12, 0))
        self.direction = tk.StringVar(value="cw")
        ttk.Label(form, text="数值增大方向").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.direction, values=("cw", "ccw"), state="readonly", width=13).grid(row=4, column=1)
        ttk.Label(panel, text="cw 顺时针    ccw 逆时针").pack(anchor="w")
        self.threshold_mode = tk.StringVar(value="otsu")
        self.polarity = tk.StringVar(value="dark")
        settings = ttk.Frame(panel)
        settings.pack(fill="x", pady=(12, 4))
        ttk.Label(settings, text="二值化").grid(row=0, column=0, sticky="w")
        ttk.Combobox(settings, textvariable=self.threshold_mode, values=("otsu", "adaptive", "fixed"), state="readonly", width=13).grid(row=0, column=1, padx=10)
        ttk.Label(settings, text="指针颜色").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Combobox(settings, textvariable=self.polarity, values=("dark", "light"), state="readonly", width=13).grid(row=1, column=1)
        ttk.Label(panel, text="dark 深色    light 浅色\n固定阈值默认 110，更多参数可用命令行。", wraplength=295).pack(anchor="w", pady=(0, 6))
        self.use_circle = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="霍夫圆修正圆心与半径", variable=self.use_circle).pack(anchor="w", pady=4)
        button("3  识别并导出各步骤", self.run_single)
        button("批量识别同机位图片", self.run_batch)
        button("批量识别（逐图标定 JSON）", self.run_batch_calibrations)
        button("显示原图", self.show_original)
        ttk.Separator(panel).pack(fill="x", pady=12)
        ttk.Label(panel, textvariable=self.result_text, wraplength=295, justify="left").pack(anchor="w")
        ttk.Label(root, textvariable=self.status, padding=(12, 8), wraplength=1080).grid(row=1, column=0, columnspan=2, sticky="ew")
        self.root.after(100, self.poll)

    def open_image(self):
        path = filedialog.askopenfilename(filetypes=[("仪表图片", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"), ("所有文件", "*")])
        if not path:
            return
        try:
            self.set_image(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("打开失败", str(exc))

    def set_image(self, path):
        image = read_image(path)
        self.path, self.image = Path(path), image
        self.calibrating = False
        self.clicks = []
        # 人工读数属于具体照片，换图时清空，避免误用上一张的参考值。
        # 此处保留已有标定，供同机位复用；不同表盘需由使用者重新载入/标定。
        self.fields["manual_value"].set("")
        self.result_text.set("尚未识别")
        self.show_original()
        self.status.set("照片已打开。不同表盘或不同机位请重新标定；同机位可复用已载入标定。")

    def show_original(self):
        if self.image is not None:
            self.shown = Image.fromarray(cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB))
            self.redraw()

    def redraw(self):
        if self.shown is None:
            return
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        w, h = self.shown.size
        # 显示时等比例缩放并居中；点击坐标需要按相同 scale/offset 换回原图。
        self.scale = min(cw / w, ch / h)
        dw, dh = max(1, round(w * self.scale)), max(1, round(h * self.scale))
        self.offset = ((cw - dw) / 2, (ch - dh) / 2)
        # 保留 PhotoImage 的实例引用，否则 Python 回收后画布图片会消失。
        self.photo = ImageTk.PhotoImage(self.shown.resize((dw, dh), Image.Resampling.LANCZOS))
        self.canvas.delete("all")
        self.canvas.create_image(*self.offset, anchor="nw", image=self.photo)
        if self.calibrating:
            for i, (x, y) in enumerate(self.clicks):
                sx, sy = self.offset[0] + x * self.scale, self.offset[1] + y * self.scale
                self.canvas.create_oval(sx-5, sy-5, sx+5, sy+5, outline="#e52222", width=2)
                self.canvas.create_text(sx+10, sy-10, text=str(i+1), fill="#e52222")

    def start_calibration(self):
        if self.image is None:
            messagebox.showinfo("提示", "请先选择仪表照片")
            return
        self.clicks = []
        self.calibrating = True
        self.show_original()
        self.status.set("第 1/4 点：点击指针旋转中心。")

    def on_click(self, event):
        if not self.calibrating or self.busy:
            return
        # event 是画布坐标，标定计算必须使用未缩放的原图坐标。
        x, y = (event.x - self.offset[0]) / self.scale, (event.y - self.offset[1]) / self.scale
        h, w = self.image.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return
        if len(self.clicks) >= 2 and math.hypot(x-self.clicks[0][0], y-self.clicks[0][1]) < 3:
            self.status.set("刻度端点不能选在圆心，请点击刻度所在方向。")
            return
        self.clicks.append((x, y))
        prompts = ["", "第 2/4 点：点击表盘外圆边缘，确定半径。", "第 3/4 点：点击最小刻度所在位置。", "第 4/4 点：点击最大刻度所在位置。"]
        if len(self.clicks) < 4:
            self.status.set(prompts[len(self.clicks)])
            self.redraw()
            return
        # 四点顺序：旋转中心、外圆边缘、最小刻度、最大刻度；文字输入补全量程。
        (cx, cy), (rx, ry), (sx, sy), (ex, ey) = self.clicks
        self.cal = Calibration(center_x=cx/w, center_y=cy/h, radius=math.hypot(rx-cx, ry-cy)/min(w,h),
                               start_angle=angle_at(cx, cy, sx, sy), end_angle=angle_at(cx, cy, ex, ey))
        self.calibrating = False
        self.redraw()
        try:
            cal = self.current_calibration()
            self.status.set(f"标定完成：起点 {cal.start_angle:.1f}°，终点 {cal.end_angle:.1f}°，有效转角 {cal.span:.1f}°。请确认最小值、最大值和方向。")
        except ValueError as exc:
            self.cal = None
            messagebox.showerror("标定无效", str(exc))

    def current_calibration(self):
        if self.cal is None or self.calibrating:
            raise ValueError("请完成四点标定或载入标定 JSON")
        # 基础几何与表单中的量程/单位合并为新对象，保留原标定对象供继续编辑。
        cal = replace(self.cal, min_value=float(self.fields["min_value"].get()),
                      max_value=float(self.fields["max_value"].get()), unit=self.fields["unit"].get(),
                      direction=self.direction.get())
        cal.validate()
        return cal

    def load_calibration(self):
        path = filedialog.askopenfilename(filetypes=[("标定文件", "*.json")])
        if not path:
            return
        try:
            self.cal = Calibration.load(path)
            self.calibrating = False
            for key in ("min_value", "max_value", "unit"):
                self.fields[key].set(str(getattr(self.cal, key)))
            self.direction.set(self.cal.direction)
            self.status.set("已载入标定。请确认当前照片与标定照片的机位、方向和裁剪一致。")
        except (ValueError, OSError, TypeError) as exc:
            messagebox.showerror("载入失败", str(exc))

    def save_calibration(self):
        # 此按钮只保存 Calibration 字段；人工读数不属于可跨照片复用的标定。
        try:
            cal = self.current_calibration()
            path = filedialog.asksaveasfilename(defaultextension=".json", initialfile="calibration.json")
            if path:
                cal.save(path)
                self.status.set(f"标定已保存：{path}")
        except (ValueError, OSError) as exc:
            messagebox.showerror("保存失败", str(exc))

    def current_params(self):
        return Params(threshold_mode=self.threshold_mode.get(), polarity=self.polarity.get())

    def start_job(self, fn):
        # 禁用按钮防止重复提交；耗时图像计算在后台执行，界面保持响应。
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")
        self.status.set("正在处理并导出结果，请稍候……")
        def worker():
            try:
                self.events.put((True, fn()))
            except Exception as exc:
                self.events.put((False, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def run_single(self):
        if self.path is None:
            messagebox.showinfo("提示", "请先选择图片")
            return
        try:
            cal, params = self.current_calibration(), self.current_params()
            manual = self.fields["manual_value"].get().strip()
            manual = float(manual) if manual else None
        except ValueError as exc:
            messagebox.showerror("参数有误", str(exc))
            return
        dest = filedialog.askdirectory(title="选择结果保存文件夹")
        if not dest:
            return
        out = Path(dest) / f"{self.path.stem}_{datetime.now():%Y%m%d_%H%M%S}"
        # 在主线程读取控件值并固定本次输入；后台任务不再访问 Tk 变量。
        path, use_circle = self.path, self.use_circle.get()
        self.start_job(lambda: ("single", analyze(path, cal, out, params, manual, use_circle), out))

    def run_batch(self):
        # 共用标定模式：当前载入/编辑的标定用于文件夹中的全部照片。
        try:
            cal, params = self.current_calibration(), self.current_params()
        except ValueError as exc:
            messagebox.showerror("参数有误", str(exc))
            return
        folder = filedialog.askdirectory(title="选择同机位仪表照片文件夹")
        if not folder:
            return
        dest = filedialog.askdirectory(title="选择批量结果保存文件夹")
        if not dest:
            return
        out = Path(dest) / f"batch_{datetime.now():%Y%m%d_%H%M%S}"
        use_circle = self.use_circle.get()
        self.start_job(lambda: ("batch", batch_read(folder, cal, out, params, use_auto_circle=use_circle), out))

    def run_batch_calibrations(self):
        """不同照片使用各自 JSON，无需先加载当前图片或共用标定。"""
        folder = filedialog.askdirectory(title="选择原始图片文件夹（例如 experiments_image/image）")
        if not folder:
            return
        calibration_dir = filedialog.askdirectory(title="选择逐图标定 JSON 文件夹（例如 experiments_image/calibration.json）")
        if not calibration_dir:
            return
        dest = filedialog.askdirectory(title="选择批量结果保存文件夹")
        if not dest:
            return
        # None 表示没有共用标定，由 batch_read 在所选目录中逐张匹配 JSON。
        # 公共处理参数可被同目录中的逐图 .params.json 覆盖。
        params = self.current_params()
        use_circle = self.use_circle.get()
        out = Path(dest) / f"batch_{datetime.now():%Y%m%d_%H%M%S_%f}"
        self.start_job(lambda: ("batch", batch_read(
            folder, None, out, params, use_auto_circle=use_circle,
            calibration_dir=calibration_dir), out))

    def poll(self):
        # 每 100 ms 在主线程检查队列；识别失败与后台异常分别显示，不把旧图当新结果。
        try:
            ok, data = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button in self.buttons:
                button.configure(state="normal")
            if not ok:
                self.show_original()
                self.status.set("处理失败，请检查参数。")
                messagebox.showerror("处理失败", data)
            else:
                kind, result, out = data
                if kind == "batch":
                    n = sum(r["status"] == "ok" for r in result)
                    self.result_text.set(f"批处理完成\n输出读数 {n}/{len(result)}，失败 {len(result)-n}\n详细结果及失败原因见 summary.csv\n输出读数不等于已验证准确")
                elif result["status"] == "ok":
                    self.result_text.set(f"读数 {result['reading']:.4f} {result['unit']}\n角度 {result['angle_deg']:.2f}°\n径向支持 {result['ray_support']:.3f}\n支持度不等于正确概率")
                    with Image.open(out / "09_result.png") as im:
                        self.shown = im.convert("RGB")
                    self.redraw()
                else:
                    self.show_original()
                    self.result_text.set("未输出读数\n" + result.get("error", "未知原因"))
                self.status.set(f"结果已保存：{out}")
        self.root.after(100, self.poll)


def main():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise SystemExit(f"GUI 启动失败：{exc}\n请在有桌面的电脑运行；无桌面环境请使用 gauge_reader.py。")
    GaugeApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
