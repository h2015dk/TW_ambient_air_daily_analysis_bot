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

ITEMS = ["PM2.5", "NOx", "SO2", "WIND_DIREC", "WIND_SPEED", "WD_HR", "WS_HR"]
HIGHLIGHT = {"雲嘉南": {"SO2": "嘉義"}}             # 額外指定疊圖比較的測站：{空品區: {測項: 測站}}
ZONE_FILE = {"北部": "north", "竹苗": "zhumiao", "中部": "central", "雲嘉南": "yunjianan",
             "高屏": "gaoping", "宜蘭": "yilan", "花東": "huadong"}
SEND_GROUPS = [["北部", "竹苗"], ["中部", "雲嘉南"], ["高屏"], ["宜蘭", "花東"]]   # 分 4 次發送
UNITS = {"PM2.5": "μg/m³", "NOx": "ppb", "SO2": "ppb"}
MARK_COLOR = {"PM2.5": "red", "NOx": "blue", "SO2": "green"}   # 風向圖上最高測站標記的顏色

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
    st["areaname"] = st["areaname"].astype(str).str.replace("空品區", "", regex=False).str.strip()
    st["lon"] = pd.to_numeric(st["twd97lon"], errors="coerce")     # 經緯度（度），用來找最近的風向測站
    st["lat"] = pd.to_numeric(st["twd97lat"], errors="coerce")
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
    merged = long.merge(st[["siteid", "areaname", "county", "lon", "lat"]], on="siteid", how="left")
    miss = merged["areaname"].isna().mean()
    print(f"測站對應失敗比例: {miss:.0%}")
    print("aqx_p_13 的 siteid 範例:", sorted(long["siteid"].unique())[:5])
    print("aqx_p_07 的 siteid 範例:", sorted(st["siteid"].unique())[:5])
    return merged


def top_site(z, item, unit):
    """回傳某測項「日均最高測站」的文字（有效時數 < 18 的測站不比較）"""
    s = z[z["itemengname"] == item].groupby(["sitename", "county"])["v"].agg(
        mean="mean", n="count", peak="max")
    s = s[s["n"] >= 18]
    if s.empty:
        return f"{item} 最高：有效資料不足"
    idx = s["mean"].idxmax()
    r = s.loc[idx]
    return (f"{item} 最高：{idx[0]}（{idx[1]}）\n"
            f"  日均 {r['mean']:.1f} {unit}｜小時最高 {r['peak']:.1f}")


def find_top(z, item, min_hours=18):
    """回傳某測項日均最高的測站名稱（有效時數不足 min_hours 的不比較），沒有則回傳 None"""
    s = z[z["itemengname"] == item].groupby("sitename")["v"].agg(mean="mean", n="count")
    s = s[s["n"] >= min_hours]
    return None if s.empty else s["mean"].idxmax()


def km(lat1, lon1, lat2, lon2):
    """兩點距離（公里，haversine）"""
    r = np.pi / 180
    a = (np.sin((lat2 - lat1) * r / 2) ** 2
         + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin((lon2 - lon1) * r / 2) ** 2)
    return 12742 * np.arcsin(np.sqrt(a))


def wind_at(z, wd_name, ws_name, site, hour):
    """回傳 (風向角度, 風速, 來源說明)；找不到風向回傳 None。
    1. 該測站該小時有風向 → 用本站
    2. 沒有 → 用同空品區該小時「距離最近」且有風向的測站
    3. 沒有座標可算距離 → 用全區風速加權合成風向"""
    zw = z[z["itemengname"].isin([wd_name, ws_name]) & (z["hour"] == hour)]
    p = zw.pivot_table(index="sitename", columns="itemengname", values="v", aggfunc="mean")
    if wd_name not in p:
        return None
    p = p.dropna(subset=[wd_name])
    if p.empty:
        return None

    def spd_of(name):
        if ws_name in p and pd.notna(p.loc[name, ws_name]):
            return float(p.loc[name, ws_name])
        return None

    if site in p.index:
        return float(p.loc[site, wd_name]) % 360, spd_of(site), "本站"

    pos = z.drop_duplicates("sitename").set_index("sitename")[["lat", "lon"]]
    if site in pos.index and pos.loc[site].notna().all():
        cand = [n for n in p.index if n in pos.index and pos.loc[n].notna().all()]
        if cand:
            dist = {n: km(pos.loc[site, "lat"], pos.loc[site, "lon"],
                          pos.loc[n, "lat"], pos.loc[n, "lon"]) for n in cand}
            near = min(dist, key=dist.get)
            return (float(p.loc[near, wd_name]) % 360, spd_of(near),
                    f"{near}站，距{dist[near]:.1f} km")

    spd = p[ws_name].fillna(1).values if ws_name in p else np.ones(len(p))
    rad = np.deg2rad(p[wd_name].values)
    wd = (np.rad2deg(np.arctan2((spd * np.sin(rad)).sum(), (spd * np.cos(rad)).sum())) + 360) % 360
    return float(wd), (float(p[ws_name].mean()) if ws_name in p else None), "全區合成"


def wrap_items(prefix, items, width=78):
    """用『、』串接項目並手動換行（中文沒有空白，textwrap 會從字中間硬切）"""
    lines, cur = [], prefix
    for i, it in enumerate(items):
        piece = it + ("、" if i < len(items) - 1 else "")
        if len(cur) + len(piece) > width and cur.strip():
            lines.append(cur)
            cur = "　　" + piece               # 換行後縮排兩個全形空白
        else:
            cur += piece
    lines.append(cur)
    return lines


def station_footer(z, wd_name):
    """列出有統計的測站（該測項至少有一筆有效值），依縣市分組；並標出缺哪些測項"""
    def names(item):
        d = z[(z["itemengname"] == item) & z["v"].notna()]
        return set(d["sitename"])
    sets = {"PM2.5": names("PM2.5"), "NOx": names("NOx"),
            "SO2": names("SO2"), "風向": names(wd_name)}
    used = set().union(*sets.values())
    meta = z[z["sitename"].isin(used)][["sitename", "county"]].drop_duplicates()
    lines = [f"統計測站（共 {len(used)} 站｜" +
             "｜".join(f"{k} {len(v)} 站" for k, v in sets.items()) + "）"]
    for county, g in meta.groupby("county"):
        lines += wrap_items(f"{county}：", sorted(g["sitename"]))
    for k, v in sets.items():
        miss = sorted(used - v)
        if miss:
            lines += wrap_items(f"無{k}資料：", miss)
    return lines


def make_chart(long, zone, path):
    z = long[long["areaname"] == zone]

    # 風向測項：優先用小時平均 WD_HR / WS_HR，沒有就用 WIND_DIREC / WIND_SPEED
    wd_name = "WD_HR" if z[z["itemengname"] == "WD_HR"]["v"].notna().any() else "WIND_DIREC"
    ws_name = "WS_HR" if wd_name == "WD_HR" else "WIND_SPEED"

    foot = station_footer(z, wd_name)
    foot_h = 0.16 * len(foot) + 0.12            # 每行約 0.16 吋，再加一點緩衝
    H = 10 + foot_h
    fig = plt.figure(figsize=(10, H))
    gs = fig.add_gridspec(3, 2, width_ratios=[2, 1.3])

    peaks = {}                                  # {測項: (最高測站, 最高值的小時, 最高值)}

    # 左：PM2.5 / NOx / SO2 逐時（全區平均線 + 範圍帶 + 日均最高測站黑線）
    for i, (item, label, c) in enumerate([("PM2.5", "PM2.5 (μg/m³)", "tab:red"),
                                          ("NOx", "NOx (ppb)", "tab:blue"),
                                          ("SO2", "SO2 (ppb)", "tab:green")]):
        ax = fig.add_subplot(gs[i, 0])
        d = z[z["itemengname"] == item]                 # 平均線與範圍帶：一律用全部測站
        top = find_top(z, item)                         # 日均最高測站
        extra = HIGHLIGHT.get(zone, {}).get(item)       # 額外指定的測站（例如雲嘉南 SO2 的嘉義）

        g = d.groupby("hour")["v"].agg(["mean", "min", "max"]).reindex(range(24))
        ax.fill_between(g.index, g["min"], g["max"], color=c, alpha=.15, label="全區範圍")
        ax.plot(g.index, g["mean"], color=c, marker="o", ms=3, label="全區平均")

        def station_line(name):
            return d[d["sitename"] == name].groupby("hour")["v"].mean().reindex(range(24))

        has_line = False
        if top:
            h = station_line(top)
            ax.plot(h.index, h, color="black", marker="s", ms=3.5, lw=1.8,
                    label=f"最高：{top}（日均 {h.mean():.1f}）")
            peaks[item] = (top, int(h.idxmax()), float(h.max()))
            has_line = True
        if extra and extra != top:                      # 若嘉義剛好就是最高站，不重複畫
            h2 = station_line(extra)
            if h2.notna().any():
                ax.plot(h2.index, h2, color="tab:purple", ls="--", marker="^", ms=3.5, lw=1.6,
                        label=f"{extra}（日均 {h2.mean():.1f}）")
                has_line = True
            else:
                print(f"警告：{zone} 找不到測站「{extra}」的 {item} 資料")

        if has_line:
            ax.set_ylim(top=ax.get_ylim()[1] * 1.3)     # 上方留空間給圖例
        ax.legend(loc="upper left", fontsize=7.5, ncol=2, frameon=False)

        ax.set_ylabel(label)
        ax.set_xlim(0, 23)
        ax.set_xticks(range(0, 24, 3))
        ax.grid(alpha=.3)
        m = d["v"].mean()
        ax.set_title(f"全區日均 {m:.1f}" if pd.notna(m) else "無資料", loc="right", fontsize=10)
    ax.set_xlabel("時")

    # 右下：說明區（上：風向標記圖例；下：日均最高測站文字）
    axt = fig.add_subplot(gs[2, 1])
    axt.axis("off")

    # 右上：風向玫瑰圖
    w = z[z["itemengname"].isin([wd_name, ws_name])].pivot_table(
        index=["siteid", "hour"], columns="itemengname", values="v", aggfunc="mean"
    ).rename(columns={wd_name: "WIND_DIREC", ws_name: "WIND_SPEED"})

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
        rmax = max(counts.max(), 1)
        axp.set_ylim(0, rmax * 1.25)                    # 外圈留空間給標記
        axp.set_rlabel_position(float(np.argmin(counts) * 22.5))   # 次數刻度放在長條最短（最空）的方向
        axp.tick_params(axis="y", labelsize=8)
        for lb in axp.get_yticklabels():                # 刻度數字加白底，被長條蓋到也看得清楚
            lb.set_bbox(dict(facecolor="white", alpha=.75, edgecolor="none", pad=0.6))
        rad = np.deg2rad(deg)
        wd = (np.rad2deg(np.arctan2((spd * np.sin(rad)).mean(), (spd * np.cos(rad)).mean())) + 360) % 360
        axp.set_title(f"風向分布（徑向：次數，測站×小時）\n"
                      f"合成風向：{compass(wd)}（{wd:.0f}°）　平均風速 {spd.mean():.1f} m/s",
                      fontsize=10, pad=18)

        # 各污染物「最高測站、最高值那一小時」的風向標記，並註明該小時風速
        handles = []
        for k, item in enumerate(["PM2.5", "NOx", "SO2"]):
            if item not in peaks:
                continue
            site, hr, val = peaks[item]
            res = wind_at(z, wd_name, ws_name, site, hr)
            if res is None:
                continue
            d_deg, d_spd, src = res
            r = rmax * (1.18 - 0.08 * k)                # 三條線長度錯開，避免重疊
            th = np.deg2rad(d_deg)
            axp.plot([th, th], [0, r], color=MARK_COLOR[item], lw=2, zorder=5)
            spd_txt = f"{d_spd:.1f} m/s" if d_spd is not None else "無風速資料"
            mk, = axp.plot(th, r, marker="o", ms=8, color=MARK_COLOR[item], zorder=6, ls="",
                           label=(f"{item} {val:.1f} {UNITS[item]}｜{site} {hr}時\n"
                                  f"{compass(d_deg)} {d_deg:.0f}°｜風速 {spd_txt}｜{src}"))
            handles.append(mk)
        if handles:
            axt.legend(handles=handles, loc="upper left", bbox_to_anchor=(0, 1.0), fontsize=7.5,
                       frameon=False, borderaxespad=0, labelspacing=0.7,
                       title="最高濃度測站於最高值小時的風向、風速", title_fontsize=8,
                       alignment="left")
    else:
        axp.set_title("風向無資料", pad=18)

    txt = "前一日日均最高測站\n" + "\n".join([
        top_site(z, "PM2.5", "μg/m³"),
        top_site(z, "NOx", "ppb"),
        top_site(z, "SO2", "ppb"),
    ])
    axt.text(0, 0.0, txt, fontsize=9, va="bottom", ha="left", transform=axt.transAxes)

    fig.suptitle(f"{DAY}  {zone}空品區 空氣品質日報", fontsize=16)
    fig.tight_layout(rect=[0, foot_h / H + 0.005, 1, 1])      # 底部留空間給測站名單
    fig.text(0.02, 0.004, "\n".join(foot), fontsize=8, va="bottom", ha="left", linespacing=1.35)
    fig.savefig(path, dpi=100)
    plt.close(fig)


def build():
    long = load_data()
    os.makedirs(OUT, exist_ok=True)
    made = 0
    for zone, fn in ZONE_FILE.items():
        if long[long["areaname"] == zone].empty:
            print(f"警告：{zone} 無資料（請確認 areaname 寫法）")
            continue
        make_chart(long, zone, f"{OUT}/{fn}.png")
        made += 1
    print(f"共產出 {made} 張圖")
    if made == 0:
        sys.exit("沒有產出任何圖，請檢查上面的 areaname 與 siteid 對應")
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
    print("要發送的日期:", DAY, "| 資料夾存在:", os.path.isdir(OUT),
          "| 檔案:", os.listdir(OUT) if os.path.isdir(OUT) else [])
    gid = os.environ.get("LINE_GROUP_ID", "").strip()
    print("群組 ID 開頭:", gid[:1] or "（空）", "| 長度:", len(gid))
    for grp in SEND_GROUPS:
        msgs = []
        for zone in grp:
            fn = ZONE_FILE[zone]
            if not os.path.exists(f"{OUT}/{fn}.png"):
                print(f"略過 {zone}：找不到 {OUT}/{fn}.png")
                continue
            url = f"{base}/{fn}.png?v={int(time.time())}"
            wait_public(url)
            msgs.append({"type": "image", "originalContentUrl": url, "previewImageUrl": url})
        if not msgs:
            print("這組沒有圖片，不發送:", grp)
            continue
        r = requests.post("https://api.line.me/v2/bot/message/push",
                          headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_TOKEN'].strip()}"},
                          json={"to": gid, "messages": msgs}, timeout=30)
        print(grp, "→ LINE 回應:", r.status_code, r.text[:200])
        r.raise_for_status()
        time.sleep(1)


if __name__ == "__main__":
    {"build": build, "send": send}[sys.argv[1]]()
