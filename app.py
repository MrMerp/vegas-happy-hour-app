import json
import os
import re
import html
from datetime import time, datetime, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Vegas Happy Hour Finder", layout="wide")
st.title("🍸 Las Vegas Happy Hour Finder")

DATA_FILE = "happy_hours_raw.csv"
FAVORITES_FILE = "favorites.json"


@st.cache_data
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    # Normalize time columns
    for col in ["Start Time Clean", "End Time Clean"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.time

    # Normalize day flags to real booleans
    day_flag_cols = [
        "Is Sunday",
        "Is Monday",
        "Is Tuesday",
        "Is Wednesday",
        "Is Thursday",
        "Is Friday",
        "Is Saturday",
    ]
    for col in day_flag_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.strip()
                .str.upper()
                .isin(["TRUE", "T", "YES", "Y", "1"])
            )

    # Numeric helper
    if "Drink Min Price" in df.columns:
        df["Drink Min Price"] = pd.to_numeric(df["Drink Min Price"], errors="coerce")

    # All-day detection
    df["Is All Day"] = False
    if "Start Time Clean" in df.columns and "End Time Clean" in df.columns:

        def is_all_day(row):
            start = row["Start Time Clean"]
            end = row["End Time Clean"]
            if pd.isna(start) or pd.isna(end):
                return False
            return start == time(0, 0) and end >= time(23, 0)

        df["Is All Day"] = df.apply(is_all_day, axis=1)

    return df


def safe_str(val) -> str:
    """Convert to clean string; hide NaN/None and normalize whitespace."""
    if val is None or pd.isna(val):
        return ""
    text = str(val).replace("\n", " ").replace("\r", " ")
    text = " ".join(text.split())
    return text.strip()


def build_fav_key(row: pd.Series) -> str:
    casino = safe_str(row.get("Casino"))
    restaurant = safe_str(row.get("Restaurant"))
    return f"{casino}::{restaurant}"


def load_favorites_from_file() -> dict:
    if not os.path.exists(FAVORITES_FILE):
        return {}
    try:
        with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_favorites_to_file(favorites: dict) -> None:
    try:
        with open(FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def fmt_time(t) -> str:
    if t is None or pd.isna(t):
        return "—"
    if isinstance(t, pd.Timestamp):
        t = t.time()
    try:
        return t.strftime("%-I:%M %p")
    except ValueError:
        return t.strftime("%I:%M %p").lstrip("0")


def fix_prices(text: str) -> str:
    """
    Add $ before obvious price numbers that are missing it.
    Keeps quantity-like patterns untouched (e.g. '3 PBR').
    """
    if not text:
        return text

    s = text

    # 1) Add $ before patterns like "5 24oz beer" (token starts with digits like 24oz)
    # Example: "5 24oz beer" -> "$5 24oz beer"
    s = re.sub(r"(?<!\$)\b(\d+)\b(?=\s+\d+oz\b)", r"$\1", s, flags=re.IGNORECASE)

    # 2) General: number + word
    # Example: "3 bottled beer" -> "$3 bottled beer"
    # But: "3 PBR" should NOT get "$" (all caps short word)
    pattern = re.compile(r"(?<!\$)\b(\d+(\.\d+)?)\b(\s+)([A-Za-z][A-Za-z0-9’'\-]*)")

    def repl(m):
        num = m.group(1)
        space = m.group(3)
        word = m.group(4)

        # Don't convert "2-for-1" / "2-for-14" style pieces
        # (we only see the first token, but if word is "for" skip)
        if word.lower() == "for":
            return f"{num}{space}{word}"

        # Skip quantity shorthand like "3 PBR", "2 BOGO", etc.
        if word.isupper() and len(word) <= 5:
            return f"{num}{space}{word}"

        # Otherwise, treat as price
        return f"${num}{space}{word}"

    s = pattern.sub(repl, s)
    return s


def render_plain_line(emoji: str, text: str) -> None:
    """
    Render as plain HTML so Streamlit never interprets markdown/emphasis/code.
    """
    safe = html.escape(text)
    st.markdown(f"<div style='margin: 0.15rem 0;'>{emoji} {safe}</div>", unsafe_allow_html=True)


# ---------- Load data ----------
try:
    df = load_data(DATA_FILE)
    st.caption(f"Loaded data from `{DATA_FILE}` with {len(df)} rows.")
except Exception as e:
    st.error(f"Failed to load `{DATA_FILE}`: {e}")
    st.stop()

# ---------- Favorites init ----------
if "favorites" not in st.session_state:
    st.session_state["favorites"] = load_favorites_from_file()

# ======================
# Sidebar filters
# ======================
st.sidebar.header("Filters")

mobile_view = st.sidebar.checkbox("Mobile view (compact cards)", value=False)

zone_col = "Location Zone"
zone_choice = "Any"
if zone_col in df.columns:
    zone_options = ["Any"] + sorted(df[zone_col].dropna().unique().tolist())
    zone_choice = st.sidebar.selectbox("Location Zone", zone_options, index=0)

casino_col = "Casino"
casino_choice = "Any"
if casino_col in df.columns:
    if zone_choice != "Any" and zone_col in df.columns:
        casino_base = df[df[zone_col] == zone_choice]
    else:
        casino_base = df
    casino_options = ["Any"] + sorted(casino_base[casino_col].dropna().unique().tolist())
    casino_choice = st.sidebar.selectbox("Casino", casino_options, index=0)

DAY_FLAGS = {
    "Sunday": "Is Sunday",
    "Monday": "Is Monday",
    "Tuesday": "Is Tuesday",
    "Wednesday": "Is Wednesday",
    "Thursday": "Is Thursday",
    "Friday": "Is Friday",
    "Saturday": "Is Saturday",
}
day_options = ["Any"] + list(DAY_FLAGS.keys())

default_time = time(19, 0)

if "day_choice" not in st.session_state or st.session_state["day_choice"] not in day_options:
    st.session_state["day_choice"] = "Any"
if "time_choice" not in st.session_state:
    st.session_state["time_choice"] = default_time

selected_day = st.sidebar.selectbox(
    "Day of Week",
    day_options,
    index=day_options.index(st.session_state["day_choice"]),
)

selected_time = st.sidebar.time_input(
    "Time of day",
    value=st.session_state["time_choice"],
)

st.session_state["day_choice"] = selected_day
st.session_state["time_choice"] = selected_time

# Quick buttons
col_now, col_tonight = st.sidebar.columns(2)

with col_now:
    if st.button("NOW"):
        now = datetime.now()
        st.session_state["time_choice"] = now.time().replace(microsecond=0)
        wd = now.strftime("%A")
        if wd in DAY_FLAGS:
            st.session_state["day_choice"] = wd
        st.rerun()

with col_tonight:
    if st.button("TONIGHT"):
        today = datetime.now()
        st.session_state["time_choice"] = time(19, 0)
        wd = today.strftime("%A")
        if wd in DAY_FLAGS:
            st.session_state["day_choice"] = wd
        st.rerun()

col_tom_afternoon, col_tom_night = st.sidebar.columns(2)

with col_tom_afternoon:
    if st.button("Tomorrow Afternoon"):
        tomorrow = datetime.now() + timedelta(days=1)
        st.session_state["time_choice"] = time(15, 0)
        wd = tomorrow.strftime("%A")
        if wd in DAY_FLAGS:
            st.session_state["day_choice"] = wd
        st.rerun()

with col_tom_night:
    if st.button("Tomorrow Night"):
        tomorrow = datetime.now() + timedelta(days=1)
        st.session_state["time_choice"] = time(19, 0)
        wd = tomorrow.strftime("%A")
        if wd in DAY_FLAGS:
            st.session_state["day_choice"] = wd
        st.rerun()

day_choice = st.session_state["day_choice"]
selected_time = st.session_state["time_choice"]

all_day_only = st.sidebar.checkbox("Show only all-day happy hours", value=False)
show_favorites_only = st.sidebar.checkbox("Show favorites only", value=False)

max_drink_budget = None
if "Drink Min Price" in df.columns:
    valid = df["Drink Min Price"].dropna()
    if not valid.empty:
        max_drink_budget = st.sidebar.slider(
            "Max cheapest drink ($)",
            min_value=float(valid.min()),
            max_value=float(valid.max()),
            value=float(valid.max()),
            step=1.0,
        )

# ======================
# Apply filters
# ======================
filtered = df.copy()

if zone_choice != "Any" and zone_col in filtered.columns:
    filtered = filtered[filtered[zone_col] == zone_choice]

if casino_choice != "Any" and casino_col in filtered.columns:
    filtered = filtered[filtered[casino_col] == casino_choice]

if all_day_only and "Is All Day" in filtered.columns:
    filtered = filtered[filtered["Is All Day"] == True]

if day_choice != "Any":
    flag_col = DAY_FLAGS[day_choice]
    if flag_col in filtered.columns:
        filtered = filtered[filtered[flag_col] == True]

# Time window: END is EXCLUSIVE (so End=7:00 PM won't show at 7:00 PM)
if "Start Time Clean" in filtered.columns and "End Time Clean" in filtered.columns:

    def in_window(row):
        start = row["Start Time Clean"]
        end = row["End Time Clean"]
        if pd.isna(start) or pd.isna(end):
            return False
        if start <= end:
            return start <= selected_time < end
        return (selected_time >= start) or (selected_time < end)

    filtered = filtered[filtered.apply(in_window, axis=1)]

if max_drink_budget is not None and "Drink Min Price" in filtered.columns:
    filtered = filtered[
        filtered["Drink Min Price"].notna()
        & (filtered["Drink Min Price"] <= max_drink_budget)
    ]

favorites_dict = st.session_state.get("favorites", {})
fav_keys = set(favorites_dict.keys())

if show_favorites_only:
    if fav_keys:
        filtered = filtered[filtered.apply(lambda r: build_fav_key(r) in fav_keys, axis=1)]
    else:
        filtered = filtered.iloc[0:0]

# ======================
# Display
# ======================
st.subheader("✅ Matching Happy Hours")

if filtered.empty:
    st.warning("No happy hours match your filters. Try adjusting time, zone, casino, budget, or day.")
    st.stop()

st.write(f"{len(filtered)} result(s)")

sort_by = []
ascending = []
if "Location Zone" in filtered.columns:
    sort_by.append("Location Zone")
    ascending.append(True)
if "Drink Min Price" in filtered.columns:
    sort_by.append("Drink Min Price")
    ascending.append(True)

sorted_df = filtered.sort_values(by=sort_by, ascending=ascending, na_position="last") if sort_by else filtered

favorites = st.session_state.get("favorites", {})

if mobile_view:
    st.caption("📱 Mobile card view: tap ⭐ to favorite (stored in favorites.json on the server).")

    new_fav_keys = []

    for idx, row in sorted_df.iterrows():
        key = build_fav_key(row)
        is_fav = key in favorites

        restaurant = safe_str(row.get("Restaurant"))
        casino = safe_str(row.get("Casino"))
        zone = safe_str(row.get("Location Zone"))
        day_label = safe_str(row.get("Day of Week"))

        drinks_text = safe_str(row.get("Drinks"))
        food_text = safe_str(row.get("Food"))

        start_str = fmt_time(row.get("Start Time Clean"))
        end_str = fmt_time(row.get("End Time Clean"))

        with st.container(border=True):
            col_text, col_fav = st.columns([6, 1])

            with col_text:
                parts = []
                if zone:
                    parts.append(f"**{zone}**")
                if casino:
                    parts.append(casino)
                if restaurant:
                    parts.append(restaurant)
                st.markdown(" · ".join(parts) if parts else "Unknown location")

            with col_fav:
                fav_checked = st.checkbox(
                    "⭐",
                    value=is_fav,
                    key=f"fav_mobile_{key}_{idx}",
                    label_visibility="collapsed",
                )

            top_line_bits = []
            if day_label:
                top_line_bits.append(day_label)
            top_line_bits.append(f"{start_str}–{end_str}")
            st.markdown(" • ".join([b for b in top_line_bits if b]))

            # Render drinks/food as PLAIN HTML text (no markdown parsing)
            if drinks_text:
                render_plain_line("🍹", fix_prices(drinks_text))

            if food_text and food_text != "—":
                render_plain_line("🍽️", food_text)

            if fav_checked:
                new_fav_keys.append(key)

    # Save favorites from mobile view
    old = st.session_state.get("favorites", {})
    st.session_state["favorites"] = {k: old.get(k, {"tags": []}) for k in new_fav_keys}
    save_favorites_to_file(st.session_state["favorites"])

else:
    # Desktop table view
    display_cols = [
        "Location Zone",
        "Casino",
        "Restaurant",
        "Day of Week",
        "Start Time Clean",
        "End Time Clean",
        "Drinks",
        "Food",
        "Cheapest Drink",
        "Cheapest Food Item",
    ]
    display_cols = [c for c in display_cols if c in sorted_df.columns]

    display_df = sorted_df[display_cols].copy()
    display_df.index = sorted_df.apply(build_fav_key, axis=1)
    display_df.index.name = "favorite_key"

    display_df["Favorite"] = display_df.index.to_series().apply(lambda k: k in favorites)

    ordered_cols = ["Favorite"] + [c for c in display_cols if c in display_df.columns]
    display_df = display_df[ordered_cols]

    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Favorite": st.column_config.CheckboxColumn("⭐ Favorite"),
            "Start Time Clean": st.column_config.TimeColumn("Start Time", format="h:mm A"),
            "End Time Clean": st.column_config.TimeColumn("End Time", format="h:mm A"),
        },
    )

    if "Favorite" in edited_df.columns:
        new_keys = edited_df.index[edited_df["Favorite"]].tolist()
        old = st.session_state.get("favorites", {})
        st.session_state["favorites"] = {k: old.get(k, {"tags": []}) for k in new_keys}
        save_favorites_to_file(st.session_state["favorites"])
