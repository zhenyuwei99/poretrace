import numpy as np

from .reader import Bundle


class HekaFile:
    """HEKA Patchmaster .dat 文件读取器。

    用法:
        rec = HekaFile("data.dat")
        rec.list()                                  # 查看全部 series
        n = rec.n_sweeps("-200mv-kcl")              # 该 series 有多少个 sweep
        t, y = rec.get("-200mv-kcl", sweep=5, unit="pA")

    label 支持两种模式:
        字符串 -> 标签模式, 按名称匹配 (重名时用 occurrence 选第几个)
        数字   -> 顺序模式, 直接指定第几个 series (对应 list() 中的序号)
    """

    # 按物理量分族: 换算只允许同族内进行, 跨族报错 (V 通道不能要 pA)
    _UNIT_FAMILIES = {
        "A": {"A": 1.0, "mA": 1e-3, "uA": 1e-6, "µA": 1e-6, "nA": 1e-9, "pA": 1e-12},
        "V": {"V": 1.0, "mV": 1e-3, "uV": 1e-6, "µV": 1e-6},
    }

    def __init__(self, path):
        self.path = path
        self.bundle = Bundle(path)
        self.pul = self.bundle.pul

    def _resolve(self, label, occurrence=0, group=0):
        """把 label (str|按标签 / int|按顺序) 解析成 series 索引。"""
        if isinstance(label, int):
            return label
        matches = [s for s, ser in enumerate(self.pul[group])
                   if ser.Label == label]
        if not matches:
            raise KeyError(f"no series labeled {label!r}")
        if occurrence >= len(matches):
            raise IndexError(
                f"{label!r} has {len(matches)} matches, "
                f"occurrence={occurrence} out of range")
        return matches[occurrence]

    def get(self, label, sweep=0, trace=0, occurrence=0, group=0, unit="A"):
        """读取一条记录。

        返回 (t, y): 时间轴数组 (s) + 信号数组 (按 unit 换算)。
        sweep: 该 series 下的第几次重复采集 (0 起)
        trace: 通道号 (本数据只有 Imon-4, 保持 0)
        电压钳通道原生 A, 电流钳通道原生 V; unit 需与原生同族,
        同族内可任意换算 (如 V -> 'mV'/'uV')。
        """
        s = self._resolve(label, occurrence, group)
        meta = self.pul[group][s][sweep][trace]
        y = self.bundle.data[group, s, sweep, trace]
        native = meta.YUnit
        if native == unit:
            scale = 1.0
        else:
            table = next((t for t in self._UNIT_FAMILIES.values() if native in t), None)
            if table is None or unit not in table:
                raise ValueError(f"unsupported unit {unit!r} (native {native!r})")
            scale = table[native] / table[unit]
        t = meta.XStart + np.arange(meta.DataPoints) * meta.XInterval
        return t, y * scale

    def n_sweeps(self, label, occurrence=0, group=0):
        """返回指定 series 包含的 sweep 数。"""
        return len(self.pul[group][self._resolve(label, occurrence, group)])

    def list(self, group=0):
        """打印全部 series: 序号、标签、sweep 数、点数、采样间隔、单位。"""
        for s, ser in enumerate(self.pul[group]):
            tr0 = ser[0][0]
            print(f"[{s:>2}] {ser.Label!r}: {len(ser)} sweeps, "
                  f"{tr0.DataPoints} pts, dt={tr0.XInterval:g}{tr0.XUnit}, "
                  f"Y={tr0.YUnit}")
