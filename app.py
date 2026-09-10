import streamlit as st

import store

st.set_page_config(page_title="Vic Freight Tracker", page_icon="🚚", layout="wide")
store.init_db()

st.title("🚚 Vic Freight Tracker")

pages = [
    st.Page("views/dashboard.py", title="Dashboard", icon="📊", default=True),
    st.Page("views/upload.py", title="Add manifest", icon="📤"),
    st.Page("views/settings.py", title="Settings", icon="⚙️"),
]

st.navigation(pages).run()
