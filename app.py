import json
import os
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

    # --- Normalize time columns ---
    for col in ["Start Time Clean", "End Time Clean"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.time

    # --- Normalize day-flag columns to proper booleans ---
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

    # --- Numeric drink price helper ---
    if "Drink Min Price" in df.columns:
        df["Drink Min Price"] = pd.to_numeric(df["Drink Min Price"], errors="coerce")

    # --- All-day flag (e.g. 12:00 AM–11:59 PM) ---
    df["Is All Day"] = False
    if "Start Time Clean" in df.columns and "End Time Clean" in df.columns:

        def is_all_day(row):
            start = row["Start Time Clean"]
            end = row["End Time Clean"]
            if pd.isna(start) or pd.isna(end):
                return False
            # Treat midnight to late night as "all day"
            return start == time(0, 0) and end >= time(23, 0)

        df["Is All Day"] = df.apply(is_all_day, axis=1)

    return df


def build_fav_key(row: pd.Series) -> str:
    """Stable key for a bar/restaurant used for favorites."""
    casino = str(row.get("Casino", "")).strip()
    restaurant = str(row.get("Restaurant", "")).strip()
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
        # If file saving fails, we silently ignore for now
        pass


# ---------- Load data ----------
try:
    df = load_data(DATA_FILE)
    st.caption(f"Loaded data from `{DATA_FILE}` with {len(df)} rows.")
except Exception as e:
    st.error(f"Failed to load `{DATA_FILE}`: {e}")
    st.stop()

# ---------- Favorites init (from JSON file on disk) ----------
if "favorites" not in st.session_state:
    st.session_state["favorites"] = load_favorites_from_file()

# ======================
# Sidebar filters
# ======================

st.sidebar.header("Filters")

# Mobile view toggle
mobile_view = st.sidebar.checkbox("Mobile view (compact)", value=False)

# Location / Zone filter
zone_col = "Location Zone"
if zone_col in df.columns:
    zone_options = ["Any"] + sorted(df[zone_col].dropna().unique().tolist())
    zone_choice = st.sidebar.selectbox("Location Zone", zone_options, index=0)
else:
    zone_choice = "Any"

# Day-of-week mapping
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

# ---- Session state defaults for day/time ----
default_time = time(19, 0)  # 7 PM default

if "day_choice" not in st.session_state or st.session_state["day_choice"] not in day_options:
    st.session_state["day_choice"] = "Any"

if "time_choice" not in st.session_state:
    st.session_state["time_choice"] = default_time

# ---- Day + time widgets (pull from session_state, no widget keys) ----
current_day = st.session_state["day_choice"]
current_time = st.session_state["time_choice"]

selected_day = st.sidebar.selectbox(
    "Day of Week",
    day_options,
    index=day_options.index(current_day),
)

selected_time = st.sidebar.time_input(
    "Time of day",
    value=current_time,
)

# Write back widget values to session_state
st.session_state["day_choice"] = selected_day
st.session_state["time_choice"] = selected_time

# ---- Quick-select buttons (NOW / TONIGHT / TOMORROW) ----
col_now, col_tonight = st.sidebar.columns(2)

with col_now:
    if st.button("NOW"):
        now = datetime.now()
        st.session_state["time_choice"] = now.time().replace(microsecond=0)
        weekday_name = now.strftime("%A")  # "Monday", etc.
        if weekday_name in DAY_FLAGS:
            st.session_state["day_choice"] = weekday_name
        st.rerun()

with col_tonight:
    if st.button("TONIGHT"):
        today = datetime.now()
        st.session_state["time_choice"] = time(19, 0)  # 7 PM
        weekday_name = today.strftime("%A")
        if weekday_name in DAY_FLAGS:
            st.session_state["day_choice"] = weekday_name
        st.rerun()

col_tom_afternoon, col_tom_night = st.sidebar.columns(2)

with col_tom_afternoon:
    if st.button("Tomorrow Afternoon"):
        tomorrow = datetime.now() + timedelta(days=1)
        st.session_state["time_choice"] = time(15, 0)  # 3 PM tomorrow
        weekday_name = tomorrow.strftime("%A")
        if weekday_name in DAY_FLAGS:
            st.session_state["day_choice"] = weekday_name
        st.rerun()

with col_tom_night:
    if st.button("Tomorrow Night"):
        tomorrow = datetime.now() + timedelta(days=1)
        st.session_state["time_choice"] = time(19, 0)  # 7 PM tomorrow
        weekday_name = tomorrow.strftime("%A")
        if weekday_name in DAY_FLAGS:
            st.session_state["day_choice"] = weekday_name
        st.rerun()

# Pull final values from session_state for filtering
day_choice = st.session_state["day_choice"]
selected_time = st.session_state["time_choice"]

# All-day toggle
all_day_only = st.sidebar.checkbox("Show only all-day happy hours", value=False)

# Favorites-only toggle
show_favorites_only = st.sidebar.checkbox("Show favorites only", value=False)

# Drink budget slider (Drink Min Price only)
if "Drink Min Price" in df.columns:
    valid_drink_prices = df["Drink Min Price"].dropna()
    if not valid_drink_prices.empty:
        price_min = float(valid_drink_prices.min())
        price_max = float(valid_drink_prices.max())

        max_drink_budget = st.sidebar.slider(
            "Max cheapest drink ($)",
            min_value=round(price_min, 0),
            max_value=round(price_max, 0),
            value=round(price_max, 0),
            step=1.0,
        )
    else:
        max_drink_budget = None
else:
    max_drink_budget = None

# ======================
# Apply filters
# ======================

filtered = df.copy()

# Zone filter
if zone_choice != "Any" and zone_col in filtered.columns:
    filtered = filtered[filtered[zone_col] == zone_choice]

# All-day filter
if all_day_only and "Is All Day" in filtered.columns:
    filtered = filtered[filtered["Is All Day"] == True]

# Day filter
if day_choice != "Any":
    flag_col = DAY_FLAGS[day_choice]
    if flag_col in filtered.columns:
        filtered = filtered[filtered[flag_col] == True]

# Time filter using Start Time Clean / End Time Clean
if "Start Time Clean" in filtered.columns and "End Time Clean" in filtered.columns:

    def row_is_in_window(row):
        start = row["Start Time Clean"]
        end = row["End Time Clean"]
        if pd.isna(start) or pd.isna(end):
            return False
        # Normal same-day window → END IS EXCLUSIVE
        if start <= end:
            return start <= selected_time < end
        # Overnight window (e.g. 9 PM to 2 AM) → END IS EXCLUSIVE
        return (selected_time >= start) or (selected_time < end)

    filtered = filtered[filtered.apply(row_is_in_window, axis=1)]

# Drink budget filter
if max_drink_budget is not None and "Drink Min Price" in filtered.columns:
    filtered = filtered[
        filtered["Drink Min Price"].notna()
        & (filtered["Drink Min Price"] <= max_drink_budget)
    ]

# Favorites-only filter (based on current favorites keys)
favorites_dict = st.session_state.get("favorites", {})
favorite_keys_set = set(favorites_dict.keys())

if show_favorites_only:
    if favorite_keys_set:
        filtered = filtered[
            filtered.apply(lambda r: build_fav_key(r) in favorite_keys_set, axis=1)
        ]
    else:
        # No favorites yet → empty result
        filtered = filtered.iloc[0:0]

# ======================
# Display results (with editable favorites)
# ======================

st.subheader("✅ Matching Happy Hours")

if filtered.empty:
    st.warning("No happy hours match your filters. Try adjusting time, zone, budget, or day.")
else:
    # Desktop vs mobile column sets
    if not mobile_view:
        base_display_cols = [
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
    else:
        # Compact set for mobile – tighter and more scannable
        base_display_cols = [
            "Restaurant",
            "Casino",
            "Location Zone",
            "Start Time Clean",
            "End Time Clean",
            "Cheapest Drink",
            "Drinks",
        ]

    display_cols = [c for c in base_display_cols if c in filtered.columns]

    st.write(f"{len(filtered)} result(s)")

    # Sort by zone then cheapest drink if available
    sort_by = []
    ascending = []

    if "Location Zone" in filtered.columns:
        sort_by.append("Location Zone")
        ascending.append(True)

    if "Drink Min Price" in filtered.columns:
        sort_by.append("Drink Min Price")
        ascending.append(True)

    sorted_df = filtered
    if sort_by:
        sorted_df = filtered.sort_values(
            by=sort_by,
            ascending=ascending,
            na_position="last",
        )

    # Build display df and index by favorites key
    display_df = sorted_df[display_cols].copy()
    display_df.index = sorted_df.apply(build_fav_key, axis=1)
    display_df.index.name = "favorite_key"

    # Favorite column from current favorites dict
    favorites = st.session_state.get("favorites", {})
    display_df["Favorite"] = display_df.index.to_series().apply(
        lambda key: key in favorites
    )

    # Reorder so Favorite is the first column
    ordered_cols = ["Favorite"] + [c for c in display_cols if c in display_df.columns]
    display_df = display_df[ordered_cols]

    st.caption(
        "⭐ Toggle favorites in the table below. "
        "Favorites are saved to favorites.json in this app folder."
        + (" (Compact column set for mobile view.)" if mobile_view else "")
    )

    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Favorite": st.column_config.CheckboxColumn(
                "⭐ Favorite",
                help="Save this spot to your favorites on this device",
            ),
            "Start Time Clean": st.column_config.TimeColumn(
                "Start Time",
                help="Happy hour start time",
                format="h:mm A",
            ),
            "End Time Clean": st.column_config.TimeColumn(
                "End Time",
                help="Happy hour end time",
                format="h:mm A",
            ),
        },
    )

    # Sync favorites from edited table back to session_state + file
    if "Favorite" in edited_df.columns:
        new_fav_keys = edited_df.index[edited_df["Favorite"]].tolist()
        old_favorites = st.session_state.get("favorites", {})
        new_favorites = {
            key: old_favorites.get(key, {"tags": []}) for key in new_fav_keys
        }
        st.session_state["favorites"] = new_favorites
        save_favorites_to_file(new_favorites)
