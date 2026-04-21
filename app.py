import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# -----------------------------
# CONFIG
# -----------------------------
REVIEWERS = ["Henrik", "Daniel", "Thomas", "Ahmed"]
RATING_OPTIONS = ["easy", "medium", "difficult", "irrelevant"]
SHEET_NAME = "Sheet1"  # Change if your worksheet has another name

# -----------------------------
# GOOGLE AUTH
# -----------------------------
@st.cache_resource

def get_google_clients():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=scopes,
    )

    gspread_client = gspread.authorize(creds)
    drive_service = build("drive", "v3", credentials=creds)
    return gspread_client, drive_service


# -----------------------------
# GOOGLE DRIVE
# -----------------------------
@st.cache_data(ttl=300)
def list_maps_in_folder(folder_id: str):
    _, drive_service = get_google_clients()

    files = []
    page_token = None

    while True:
        response = drive_service.files().list(
            q=(
                f"'{folder_id}' in parents and trashed = false and "
                f"(mimeType = 'image/jpeg' or mimeType = 'image/jpg' or mimeType = 'image/png')"
            ),
            fields="nextPageToken, files(id, name, mimeType)",
            orderBy="name",
            pageSize=1000,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()

        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return files


def get_drive_image_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=view&id={file_id}"


# -----------------------------
# GOOGLE SHEETS
# -----------------------------
def get_worksheet(sheet_url: str):
    gspread_client, _ = get_google_clients()
    spreadsheet = gspread_client.open_by_url(sheet_url)
    worksheet = spreadsheet.worksheet(SHEET_NAME)
    return worksheet


@st.cache_data(ttl=60)
def load_ratings_df(sheet_url: str) -> pd.DataFrame:
    worksheet = get_worksheet(sheet_url)
    records = worksheet.get_all_records()

    if not records:
        df = pd.DataFrame(columns=["Map"] + REVIEWERS)
    else:
        df = pd.DataFrame(records)

    for col in ["Map"] + REVIEWERS:
        if col not in df.columns:
            df[col] = ""

    df = df[["Map"] + REVIEWERS].fillna("")
    return df


def ensure_headers(sheet_url: str):
    worksheet = get_worksheet(sheet_url)
    header = worksheet.row_values(1)
    expected_header = ["Map"] + REVIEWERS

    if header != expected_header:
        worksheet.update("A1:E1", [expected_header])
        load_ratings_df.clear()



def find_row_for_map(worksheet, filename: str):
    values = worksheet.col_values(1)  # Column A = Map
    for i, value in enumerate(values[1:], start=2):  # Skip header row
        if str(value).strip() == filename:
            return i
    return None



def append_map_row_if_missing(sheet_url: str, filename: str):
    worksheet = get_worksheet(sheet_url)
    row_number = find_row_for_map(worksheet, filename)

    if row_number is None:
        worksheet.append_row([filename, "", "", "", ""])
        row_number = find_row_for_map(worksheet, filename)

    load_ratings_df.clear()
    return row_number



def save_rating(sheet_url: str, filename: str, reviewer: str, rating: str):
    worksheet = get_worksheet(sheet_url)
    row_number = append_map_row_if_missing(sheet_url, filename)

    reviewer_col_map = {
        "Henrik": 2,
        "Daniel": 3,
        "Thomas": 4,
        "Ahmed": 5,
    }
    col_number = reviewer_col_map[reviewer]

    worksheet.update_cell(row_number, col_number, rating)
    load_ratings_df.clear()


# -----------------------------
# REVIEW SELECTION LOGIC
# -----------------------------
def pick_next_map(files, df: pd.DataFrame, reviewer: str):
    rated_maps = set(
        df.loc[df[reviewer].astype(str).str.strip() != "", "Map"].astype(str).tolist()
    )

    remaining = [f for f in files if f["name"] not in rated_maps]
    return remaining[0] if remaining else None


# -----------------------------
# STREAMLIT UI
# -----------------------------
st.set_page_config(page_title="Map Difficulty Rater", layout="wide")
st.title("Map Difficulty Rater")
st.write("Rate each map as easy, medium, difficult, or irrelevant.")

sheet_url = st.secrets["app"]["sheet_url"]
folder_id = st.secrets["app"]["drive_folder_id"]

try:
    ensure_headers(sheet_url)
except Exception as e:
    st.error("Could not initialize the Google Sheet header.")
    st.exception(e)
    st.stop()

reviewer = st.selectbox(
    "Choose reviewer",
    REVIEWERS,
    index=None,
    placeholder="Select your name",
)

if reviewer:
    try:
        files = list_maps_in_folder(folder_id)
        df = load_ratings_df(sheet_url)
    except Exception as e:
        st.error("Could not load maps or ratings from Google services.")
        st.exception(e)
        st.stop()

    if not files:
        st.warning("No image files were found in the Drive folder.")
        st.stop()

    next_map = pick_next_map(files, df, reviewer)

    if next_map is None:
        st.success(f"{reviewer} has rated all available maps.")
        with st.expander("Show current ratings table"):
            st.dataframe(df, use_container_width=True)
        st.stop()

    st.subheader(f"Reviewer: {reviewer}")
    st.write(f"Now reviewing: **{next_map['name']}**")

    image_url = get_drive_image_url(next_map["id"])
    st.image(image_url, caption=next_map["name"], use_container_width=True)

    col1, col2, col3, col4 = st.columns(4)

    if col1.button("Easy", use_container_width=True):
        save_rating(sheet_url, next_map["name"], reviewer, "easy")
        st.rerun()

    if col2.button("Medium", use_container_width=True):
        save_rating(sheet_url, next_map["name"], reviewer, "medium")
        st.rerun()

    if col3.button("Difficult", use_container_width=True):
        save_rating(sheet_url, next_map["name"], reviewer, "difficult")
        st.rerun()

    if col4.button("Irrelevant", use_container_width=True):
        save_rating(sheet_url, next_map["name"], reviewer, "irrelevant")
        st.rerun()

    with st.expander("Show current ratings table"):
        st.dataframe(df, use_container_width=True)
else:
    st.info("Select a reviewer to begin rating maps.")
