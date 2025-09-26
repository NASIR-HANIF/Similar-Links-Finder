import streamlit as st
import subprocess
import os
import pandas as pd
import sys
import tempfile

st.title("Similar Links Finder (Web UI)")

# --- UI elements ---
uploaded_file = st.file_uploader("Input file (websites list .txt)", type=["txt"])
keyword = st.text_input("Keyword to search", value="")
mode = st.selectbox("Mode", ["loose", "strict"])
threshold = st.number_input("Threshold", min_value=0.0, max_value=5.0, value=1.2, step=0.1)
require_external = st.selectbox("Require External Links", ["yes", "no"])
output_name_input = st.text_input("Output file name (.csv)", value="results.csv")

# --- Button ---
if st.button("Run Finder"):
    if uploaded_file is not None and keyword:
        # Use deploy-safe temp folder
        temp_dir = tempfile.gettempdir()
        input_path = os.path.join(temp_dir, "temp_input.txt")
        output_path = os.path.join(temp_dir, output_name_input)

        # Save uploaded file temporarily
        with open(input_path, "wb") as f:
            f.write(uploaded_file.read())

        # Build the command with deploy-safe python executable
        cmd = [
            sys.executable, "wp_find_one_link_per_site_v2.py",
            "--sites", input_path,
            "--keyword", keyword,
            "--out", output_path,
            "--mode", mode,
            "--threshold", str(threshold),
            "--require-external", require_external
        ]

        # Optional debug
        # st.write("Running command:", " ".join(cmd))

        with st.spinner("Running script..."):
            result = subprocess.run(cmd, capture_output=True, text=True)

        # Optional debug
        # st.text(result.stdout)
        # st.text(result.stderr)

        if os.path.exists(output_path):
            st.success(f"Finished! File saved as {output_name_input}")
            try:
                df = pd.read_csv(output_path)
                st.dataframe(df)
            except Exception as e:
                st.warning(f"Could not read CSV: {e}")
            st.download_button("Download Results", open(output_path, "rb"), file_name=output_name_input)
        else:
            st.error("Output file not found.")
    else:
        st.warning("Please upload a file and enter a keyword.")
