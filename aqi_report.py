#!/usr/bin/env python3
"""用法: python aqi_report.py build   # 產圖
        python aqi_report.py send    # 推送到 LINE"""
import os, sys, time, shutil, requests
import numpy as np, pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK TC", "Noto Sans CJK JP", "Microsoft JhengHei"]
plt.rcParams["axes.unicode_minus"] = False

API = "https://data.moenv.gov.tw/api/v2"
TZ = ZoneInfo("Asia/Taipei")                       # runner 是 UTC，日期一定要用台北時區算
NOW = datetime.now(TZ)
DAY = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
PREV = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")
OUT = f"docs/images/{DAY}"

ITEMS = ["PM2.5", "NOx", "SO2", "WIND_DIREC", "WIND_SPEED"]
ZONE_FILE = {"北部": "north", "竹苗": "zhumiao", "中部": "central", "雲嘉南": "yunjianan",
             "高屏": "gaoping", "宜蘭": "yilan", "花東": "huadong"}
SEND_GROUPS = [["北部", "竹苗"], ["中部", "雲嘉南"], ["高屏"], ["宜蘭", "花東"]]   # 分 4 次發送

COMPASS = ["北", "北北東", "東北", "東北東", "東", "東南東", "東南", "南南東",
           "南", "南南西", "西南", "西南西", "西", "西北西", "西北", "北北西"]


def compass(deg):                                   # 氣象風向＝風「吹來」的方向
    return COMPASS[int((deg + 11.25) % 360 // 22.5)] + "風"


def fetch(dataset, filters=None):
    rows, offset = [], 0
    key = os.environ.get("MOENV_API_KEY", "").strip()
    if not key:
        sys.exit("MOENV_API_KEY 是空的，請檢查 GitHub Secret 名稱與內容")
    while True:
        p = {"api_key": key, "format": "json", "limit": 1000, "offset": offset}
        if filters:
            p["filters"] = filters
        for attempt in range(3):
            try:
                r = requests.get(f"{API}/{dataset}", params=p, timeout=60,
                                 headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                data = r.json()
                break
            except (requests.RequestException, ValueError) as e:
                print(f"[{dataset}] 第 {attempt + 1} 次失敗: {e}")
                try:
                    print("狀態碼:", r.status_code, "| 回應開頭:", r.text[:300].replace(key, "***"))
                except NameError:
                    pass
                if attempt == 2:
                    sys.exit(f"{dataset} 抓取失敗")
                time.sleep(5)
        # 回傳可能是 {"records": [...]} 或直接是 [...]
        recs = data if isinstance(data, list) else data.get("records", [])
        if offset == 0:
            print(f"[{dataset}] 回傳型態: {type(data).__name__}，第一筆: {str(recs[0])[:300] if recs else '（空）'}")
        rows += recs
        if len(recs) < 1000:
            break
        offset += 1000
    df = pd.DataFrame(rows)
    df.columns = df.columns.str.lower()
    return df


def load_data():
    st = fetch("aqx_p_07")
    st["siteid"] = st["siteid"].astype(str).str.strip()
    print("空品區清單:", sorted(st["areaname"].dropna().unique()))

    df = fetch("aqx_p_13", f"monitordate,GR,{PREV} 23:59:59|monitordate,LE,{DAY} 23:59:59")
    if df.empty:                                    # 篩選語法若不被接受，退回全抓再用 pandas 篩
        df = fetch("aqx_p_13")
    df = df[df["monitordate"].astype(str).str[:10] == DAY]
    if df.empty:
        sys.exit(f"{DAY} 查無資料")
    print("測項清單:", sorted(df["itemengname"].unique()))
    df = df[df["itemengname"].isin(ITEMS)].copy()

    hcols = [c for c in df.columns if c.startswith("monitorvalue")]
    long = df.melt(id_vars=["siteid", "sitename", "itemengname"], value_vars=hcols,
                   var_name="h", value_name="v")
    long["hour"] = long["h"].str[-2:].astype(int)
    long["v"] = pd.to_numeric(long["v"], errors="coerce")   # NR、# 等註記碼 → NaN
    long["siteid"] = long["siteid"].astype(str).str.strip()
    return long.merge(st[["siteid", "areaname", "county"]], on="siteid", how="left")


def make_chart(long, zone, path):
    z = long[long["areaname"] == zone]
    fig = plt.figure(figsize=(10, 9))
    gs = fig.add_gridspec(3, 2, width_ratios=[2, 1.1])

    # 左：PM2.5 / NOx / SO2 逐時（區域平均線 + 測站最小～最大範圍）
    for i, (item, label, c) in enumerate([("PM2.5", "PM2.5 (μg/m³)", "tab:red"),
                                          ("NOx", "NOx (ppb)", "tab:blue"),
                                          ("SO2", "SO2 (ppb)", "tab:green")]):
        ax = fig.add_subplot(gs[i, 0])
        d = z[z["itemengname"] == item]
        g = d.groupby("hour")["v"].agg(["mean", "min", "max"]).reindex(range(24))
        ax.fill_between(g.index, g["min"], g["max"], color=c, alpha=.15)
        ax.plot(g.index, g["mean"], color=c, marker="o", ms=3)
        ax.set_ylabel(label)
        ax.set_xlim(0, 23)
        ax.set_xticks(range(0, 24, 3))
        ax.grid(alpha=.3)
        m = d["v"].mean()
        ax.set_title(f"日平均 {m:.1f}" if pd.notna(m) else "無資料", loc="right", fontsize=10)
    ax.set_xlabel("時")

    # 右上：風向玫瑰圖 + 合成風向
    w = z[z["itemengname"].isin(["WIND_DIREC", "WIND_SPEED"])].pivot_table(
        index=["siteid", "hour"], columns="itemengname", values="v", aggfunc="mean")
    axp = fig.add_subplot(gs[0:2, 1], projection="polar")
    axp.set_theta_zero_location("N")
    axp.set_theta_direction(-1)
    if "WIND_DIREC" in w and w["WIND_DIREC"].notna().any():
        w = w.dropna(subset=["WIND_DIREC"])
        spd = w["WIND_SPEED"].fillna(1) if "WIND_SPEED" in w else pd.Series(1.0, index=w.index)
        deg = w["WIND_DIREC"].values % 360
        counts, _ = np.histogram((deg + 11.25) % 360, bins=16, range=(0, 360))
        axp.bar(np.deg2rad(np.arange(16) * 22.5), counts, width=np.deg2rad(22.5),
                color="tab:gray", edgecolor="white")
        rad = np.deg2rad(deg)                      # 風向不能直接算術平均，用風速加權的向量平均
        wd = (np.rad2deg(np.arctan2((spd * np.sin(rad)).mean(), (spd * np.cos(rad)).mean())) + 360) % 360
        axp.set_title(f"風向分布\n合成風向：{compass(wd)}（{wd:.0f}°）\n平均風速 {spd.mean():.1f} m/s",
                      fontsize=11)
    else:
        axp.set_title("風向無資料")

    # 右下：PM2.5 日均最高測站（有效小時數 < 18 的測站不參與比較）
    s = z[z["itemengname"] == "PM2.5"].groupby(["sitename", "county"])["v"].agg(
        mean="mean", n="count", peak="max")
    s = s[s["n"] >= 18]
    axt = fig.add_subplot(gs[2, 1])
    axt.axis("off")
    if s.empty:
        txt = "PM2.5 有效資料不足"
    else:
        idx = s["mean"].idxmax()
        r = s.loc[idx]
        txt = (f"前一日 PM2.5 日均最高測站\n\n{idx[0]}（{idx[1]}）\n日均 {r['mean']:.1f} μg/m³\n"
               f"小時最高 {r['peak']:.0f} μg/m³\n有效時數 {int(r['n'])}/24")
    axt.text(0, .5, txt, fontsize=12, va="center")

    fig.suptitle(f"{DAY}  {zone}空品區 空氣品質日報", fontsize=16)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def build():
    long = load_data()
    os.makedirs(OUT, exist_ok=True)
    for zone, fn in ZONE_FILE.items():
        if long[long["areaname"] == zone].empty:
            print(f"警告：{zone} 無資料（請確認 areaname 寫法）")
            continue
        make_chart(long, zone, f"{OUT}/{fn}.png")
    # 只保留最近 7 天，避免 repo 越長越大
    cutoff = (NOW - timedelta(days=8)).strftime("%Y-%m-%d")
    for d in os.listdir("docs/images"):
        if d < cutoff:
            shutil.rmtree(f"docs/images/{d}")


def wait_public(url, tries=6):
    for _ in range(tries):
        if requests.head(url, timeout=15).status_code == 200:
            return
        time.sleep(10)
    print("警告：圖片網址尚未可存取", url)


def send():
    base = (f"https://raw.githubusercontent.com/{os.environ['GITHUB_REPOSITORY']}/"
            f"{os.environ.get('GITHUB_REF_NAME', 'main')}/docs/images/{DAY}")
    for grp in SEND_GROUPS:
        msgs = []
        for zone in grp:
            fn = ZONE_FILE[zone]
            if not os.path.exists(f"{OUT}/{fn}.png"):
                continue
            url = f"{base}/{fn}.png"
            wait_public(url)
            msgs.append({"type": "image", "originalContentUrl": url, "previewImageUrl": url})
        if not msgs:
            continue
        r = requests.post("https://api.line.me/v2/bot/message/push",
                          headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_TOKEN']}"},
                          json={"to": os.environ["LINE_GROUP_ID"], "messages": msgs}, timeout=30)
        r.raise_for_status()
        time.sleep(1)


if __name__ == "__main__":
    {"build": build, "send": send}[sys.argv[1]]()
