"""IATA code -> (city, country, lat, lng). Mirrors the iOS Airports table, plus ISO country codes."""
from __future__ import annotations

import math
from typing import Optional, Tuple

AIRPORTS: dict[str, Tuple[str, str, float, float]] = {
    "ATL": ("Atlanta", "US", 33.6407, -84.4277),
    "AUS": ("Austin", "US", 30.1975, -97.6664),
    "BOS": ("Boston", "US", 42.3656, -71.0096),
    "BWI": ("Baltimore", "US", 39.1774, -76.6684),
    "CLT": ("Charlotte", "US", 35.2144, -80.9473),
    "DCA": ("Washington", "US", 38.8512, -77.0402),
    "DEN": ("Denver", "US", 39.8561, -104.6737),
    "DFW": ("Dallas", "US", 32.8998, -97.0403),
    "DTW": ("Detroit", "US", 42.2162, -83.3554),
    "EWR": ("Newark", "US", 40.6895, -74.1745),
    "FLL": ("Fort Lauderdale", "US", 26.0742, -80.1506),
    "HNL": ("Honolulu", "US", 21.3245, -157.9251),
    "IAD": ("Washington", "US", 38.9531, -77.4565),
    "IAH": ("Houston", "US", 29.9902, -95.3368),
    "JFK": ("New York", "US", 40.6413, -73.7781),
    "LAS": ("Las Vegas", "US", 36.0840, -115.1537),
    "LAX": ("Los Angeles", "US", 33.9416, -118.4085),
    "LGA": ("New York", "US", 40.7769, -73.8740),
    "MCO": ("Orlando", "US", 28.4312, -81.3081),
    "MDW": ("Chicago", "US", 41.7868, -87.7522),
    "MIA": ("Miami", "US", 25.7959, -80.2870),
    "MSP": ("Minneapolis", "US", 44.8848, -93.2223),
    "OAK": ("Oakland", "US", 37.7126, -122.2197),
    "ORD": ("Chicago", "US", 41.9742, -87.9073),
    "PDX": ("Portland", "US", 45.5898, -122.5951),
    "PHL": ("Philadelphia", "US", 39.8744, -75.2424),
    "PHX": ("Phoenix", "US", 33.4352, -112.0101),
    "SAN": ("San Diego", "US", 32.7338, -117.1933),
    "SEA": ("Seattle", "US", 47.4502, -122.3088),
    "SFO": ("San Francisco", "US", 37.6213, -122.3790),
    "SJC": ("San Jose", "US", 37.3639, -121.9289),
    "SLC": ("Salt Lake City", "US", 40.7899, -111.9791),
    "SMF": ("Sacramento", "US", 38.6951, -121.5908),
    "YVR": ("Vancouver", "CA", 49.1967, -123.1815),
    "YYZ": ("Toronto", "CA", 43.6777, -79.6248),
    "MEX": ("Mexico City", "MX", 19.4361, -99.0719),
    "CUN": ("Cancún", "MX", 21.0365, -86.8771),
    "LHR": ("London", "GB", 51.4700, -0.4543),
    "LGW": ("London", "GB", 51.1537, -0.1821),
    "CDG": ("Paris", "FR", 49.0097, 2.5479),
    "AMS": ("Amsterdam", "NL", 52.3105, 4.7683),
    "FRA": ("Frankfurt", "DE", 50.0379, 8.5622),
    "MUC": ("Munich", "DE", 48.3537, 11.7750),
    "MAD": ("Madrid", "ES", 40.4983, -3.5676),
    "BCN": ("Barcelona", "ES", 41.2974, 2.0833),
    "FCO": ("Rome", "IT", 41.8003, 12.2389),
    "ZRH": ("Zurich", "CH", 47.4582, 8.5555),
    "DUB": ("Dublin", "IE", 53.4264, -6.2499),
    "LIS": ("Lisbon", "PT", 38.7742, -9.1342),
    "IST": ("Istanbul", "TR", 41.2753, 28.7519),
    "DXB": ("Dubai", "AE", 25.2532, 55.3657),
    "DOH": ("Doha", "QA", 25.2731, 51.6081),
    "DEL": ("Delhi", "IN", 28.5562, 77.1000),
    "BOM": ("Mumbai", "IN", 19.0896, 72.8656),
    "BLR": ("Bengaluru", "IN", 13.1986, 77.7066),
    "HYD": ("Hyderabad", "IN", 17.2403, 78.4294),
    "MAA": ("Chennai", "IN", 12.9941, 80.1709),
    "SIN": ("Singapore", "SG", 1.3644, 103.9915),
    "HKG": ("Hong Kong", "HK", 22.3080, 113.9185),
    "NRT": ("Tokyo", "JP", 35.7720, 140.3929),
    "HND": ("Tokyo", "JP", 35.5494, 139.7798),
    "KIX": ("Osaka", "JP", 34.4320, 135.2304),
    "ICN": ("Seoul", "KR", 37.4602, 126.4407),
    "TPE": ("Taipei", "TW", 25.0797, 121.2342),
    "PEK": ("Beijing", "CN", 40.0799, 116.6031),
    "PVG": ("Shanghai", "CN", 31.1443, 121.8083),
    "BKK": ("Bangkok", "TH", 13.6900, 100.7501),
    "SYD": ("Sydney", "AU", -33.9399, 151.1753),
    "MEL": ("Melbourne", "AU", -37.6690, 144.8410),
    "AKL": ("Auckland", "NZ", -37.0082, 174.7850),
    "GRU": ("São Paulo", "BR", -23.4356, -46.4731),
    "EZE": ("Buenos Aires", "AR", -34.8222, -58.5358),
    "JNB": ("Johannesburg", "ZA", -26.1367, 28.2411),
    "CPT": ("Cape Town", "ZA", -33.9715, 18.6021),
    "PIT": ("Pittsburgh", "US", 40.4915, -80.2329),
    "ANC": ("Anchorage", "US", 61.1743, -149.9963),
    "FCA": ("Kalispell", "US", 48.3105, -114.2560),
    "CMH": ("Columbus", "US", 39.9980, -82.8919),
    "BER": ("Berlin", "DE", 52.3667, 13.5033),
    "VTZ": ("Visakhapatnam", "IN", 17.7212, 83.2245),
}


def lookup(code: Optional[str]) -> Optional[Tuple[str, str, float, float]]:
    return AIRPORTS.get((code or "").strip().upper())


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def route_miles(a: Optional[str], b: Optional[str]) -> Optional[float]:
    pa, pb = lookup(a), lookup(b)
    if not pa or not pb:
        return None
    return haversine_miles(pa[2], pa[3], pb[2], pb[3])


def nearest(lat: Optional[float], lng: Optional[float], max_miles: float = 250) -> Optional[str]:
    """IATA code of the closest known airport within `max_miles`, used to give a country to
    places that only have coordinates (a downtown rental station)."""
    if lat is None or lng is None:
        return None
    best = min(AIRPORTS, key=lambda c: haversine_miles(lat, lng, AIRPORTS[c][2], AIRPORTS[c][3]))
    return best if haversine_miles(lat, lng, AIRPORTS[best][2], AIRPORTS[best][3]) <= max_miles else None
