"""GPX 파일로 지도용 코스 데이터(data/course.json)를 만든다.

- 전체 경로를 약 20m 간격으로 줄여서 저장 (원본 1만 개 → 약 2천 개)
- 주요 지점(출발·도착, 신연교, 현암교, 신매대교, 춘성교) 좌표와 기상청 격자(nx, ny)를 계산
- GPS 기록 거리(약 42.45km)를 공식 거리 42.195km에 맞춰 비례 보정
- 고저도 그래프용 거리·고도 배열도 함께 저장

사용법: python scripts/build_course.py data/course.gpx data/course.json
"""
import json
import logging
import math
import sys
import xml.etree.ElementTree as ET

from kma_grid import latlon_to_grid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_course")

GPX_NS = "{http://www.topografix.com/GPX/1/1}"
OFFICIAL_KM = 42.195
# 주요 지점: 좌표(lat, lon)가 있으면 그 좌표를 그대로 쓰고, 없으면 km 위치를 경로에서 찾는다
CHECKPOINTS = [
    {"id": "start", "name": "공지천교", "km": 0.0, "kmLabel": "0km / 42.195km", "tabName": "공지천교", "tabKm": "0km",
     "desc": "공지천교", "lat": 37.873310, "lon": 127.712187, "labelDir": "right"},
    {"id": "sinyeon", "name": "신연교", "km": 8.60, "kmLabel": "약 8.60km", "tabName": "신연교", "tabKm": "8.6km",
     "desc": "신연교 부근", "lat": 37.837496, "lon": 127.674671, "labelDir": "left"},
    # 현암교: 좌표 대신 코스 15.9km 지점을 경로에서 찾아 씀
    {"id": "hyeonam", "name": "현암교", "km": 15.9, "kmLabel": "약 15.90km", "tabName": "현암교", "tabKm": "15.9km",
     "desc": "현암교 부근", "labelDir": "left"},
    {"id": "sinmae", "name": "신매대교", "km": 20.53, "kmLabel": "약 20.53km", "tabName": "신매대교", "tabKm": "20.53km",
     "desc": "신매대교 부근", "lat": 37.922061, "lon": 127.714528, "labelDir": "right"},
    {"id": "chunseong", "name": "춘성교", "km": 29.1, "kmLabel": "약 29.10km", "tabName": "춘성교", "tabKm": "29.10km",
     "desc": "춘성교 부근", "lat": 37.968384, "lon": 127.669862, "labelDir": "left"},
]
SIMPLIFY_STEP_M = 20.0

# 코스 지원 지점(CP): 공식 거리(km)와 제공 항목. 위치는 GPX 경로에서 km로 찾음(GPS 오차로 수십~수백 m 차이 가능)
AID_STATIONS = [
    {"km": 5.0, "items": ["급수대", "구급차"]},
    {"km": 10.0, "items": ["급수대", "구급차"]},
    {"km": 12.5, "items": ["스펀지"]},
    {"km": 15.0, "items": ["급수대", "구급차"]},
    {"km": 17.5, "items": ["스펀지"]},
    {"km": 20.0, "items": ["급수대", "초코파이", "구급차"]},
    {"km": 22.5, "items": ["스펀지"]},
    {"km": 25.0, "items": ["급수대", "스포츠젤", "구급차"]},
    {"km": 27.5, "items": ["스펀지"]},
    {"km": 30.0, "items": ["급수대", "바나나", "구급차"]},
    {"km": 32.5, "items": ["스펀지"]},
    {"km": 35.0, "items": ["급수대", "구급차"]},
    {"km": 37.5, "items": ["스펀지"]},
    {"km": 40.0, "items": ["급수대", "구급차"]},
]


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def read_gpx(path):
    tree = ET.parse(path)
    points = []
    for trkpt in tree.getroot().iter(GPX_NS + "trkpt"):
        ele_node = trkpt.find(GPX_NS + "ele")
        ele = float(ele_node.text) if ele_node is not None else 0.0
        points.append({"lat": float(trkpt.get("lat")), "lon": float(trkpt.get("lon")), "ele": ele})
    return points


def main(gpx_path, out_path):
    points = read_gpx(gpx_path)
    if len(points) < 2:
        logger.error("GPX 포인트가 부족합니다: %s", gpx_path)
        sys.exit(1)

    # 누적 거리 계산
    cum = [0.0]
    for i in range(1, len(points)):
        prev = points[i - 1]
        cur = points[i]
        cum.append(cum[-1] + haversine_m(prev["lat"], prev["lon"], cur["lat"], cur["lon"]))
    gps_total_m = cum[-1]
    scale = OFFICIAL_KM * 1000.0 / gps_total_m
    cum = [c * scale for c in cum]
    total_m = cum[-1]
    logger.info("포인트 %d개, GPS 거리 %.2fkm → 공식 거리 %.3fkm로 보정(x%.4f)",
                len(points), gps_total_m / 1000, total_m / 1000, scale)

    # 경로 단순화 (일정 거리마다 1개)
    track = []
    profile = []
    last_m = -SIMPLIFY_STEP_M
    for i in range(len(points)):
        if cum[i] - last_m >= SIMPLIFY_STEP_M or i == len(points) - 1:
            track.append([round(points[i]["lat"], 6), round(points[i]["lon"], 6)])
            profile.append([round(cum[i] / 1000, 3), points[i]["ele"]])
            last_m = cum[i]

    # 체크포인트
    checkpoints = []
    for spec in CHECKPOINTS:
        km = spec["km"]
        if "lat" in spec and "lon" in spec:
            # 지정 좌표 사용. 해발은 경로에서 가장 가까운 점의 고도를 씀
            idx = min(range(len(points)),
                      key=lambda j: haversine_m(spec["lat"], spec["lon"], points[j]["lat"], points[j]["lon"]))
            p = {"lat": spec["lat"], "lon": spec["lon"], "ele": points[idx]["ele"]}
            gap_m = haversine_m(spec["lat"], spec["lon"], points[idx]["lat"], points[idx]["lon"])
            logger.info("%s: 경로까지 거리 %.0fm, 경로상 %.2fkm 지점", spec["name"], gap_m, cum[idx] / 1000)
        else:
            target = km * 1000.0
            idx = len(points) - 1
            for j in range(len(cum)):
                if cum[j] >= target:
                    idx = j
                    break
            p = points[idx]
        nx, ny = latlon_to_grid(p["lat"], p["lon"])
        checkpoints.append({
            "id": spec["id"],
            "name": spec["name"],
            "km": km,
            "kmLabel": spec["kmLabel"],
            "tabName": spec["tabName"],
            "tabKm": spec["tabKm"],
            "labelDir": spec.get("labelDir", "top"),
            "desc": spec["desc"],
            "lat": round(p["lat"], 6),
            "lon": round(p["lon"], 6),
            "ele": p["ele"],
            "nx": nx,
            "ny": ny,
        })
        logger.info("%s(%.1fkm) (%.6f, %.6f) → 격자 nx=%d, ny=%d", spec["name"], km, p["lat"], p["lon"], nx, ny)

    # CP 위치: 보정된 누적 거리에서 km에 처음 닿는 지점
    aid = []
    for spec in AID_STATIONS:
        target = spec["km"] * 1000.0
        idx = len(points) - 1
        for j in range(len(cum)):
            if cum[j] >= target:
                idx = j
                break
        nx, ny = latlon_to_grid(points[idx]["lat"], points[idx]["lon"])
        aid.append({
            "km": spec["km"],
            "items": spec["items"],
            "lat": round(points[idx]["lat"], 6),
            "lon": round(points[idx]["lon"], 6),
            "ele": points[idx]["ele"],
            # CP 날씨용 기상청 격자. 4개 날씨 지점 격자 안에 모두 들어가서 API 호출은 늘지 않음
            "nx": nx,
            "ny": ny,
        })
    logger.info("CP %d곳 위치 계산", len(aid))

    course = {
        "name": "2026 춘천마라톤 풀코스",
        "raceStart": "2026-10-25T09:00:00+09:00",
        # 이 시각 이후로는 날씨 수집을 멈추고, 페이지는 날씨 대신 마무리 인사를 보여 준다
        "serviceEnd": "2026-10-25T15:00:00+09:00",
        "totalKm": OFFICIAL_KM,
        "track": track,
        "profile": profile,
        "checkpoints": checkpoints,
        "aid": aid,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(course, f, ensure_ascii=False, separators=(",", ":"))
    logger.info("저장 완료: %s (경로 %d포인트)", out_path, len(track))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        logger.error("사용법: python scripts/build_course.py <입력.gpx> <출력.json>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
