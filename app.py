import streamlit as st
import subprocess
import os
import pandas as pd

st.title("Similar Links Finder (Web UI)")

# Input file upload
uploaded_file = st.file_uploader("Input file (websites list .txt)", type=["txt"])

# Keyword input
keyword = st.text_input("Keyword to search", value="Roof repair")

# Mode select
mode = st.selectbox("Mode", ["loose", "strict"])

# Threshold input
threshold = st.number_input("Threshold", min_value=0.0, max_value=5.0, value=1.2, step=0.1)

# Require external
require_external = st.selectbox("Require External Links", ["yes", "no"])

# Output file
output_name = st.text_input("Output file name (.csv)", value="results.csv")

if st.button("Run Finder"):
    if uploaded_file is not None and keyword:
        # Save uploaded file temporarily
        input_path = os.path.join("temp_input.txt")
        with open(input_path, "wb") as f:
            f.write(uploaded_file.read())

        # Build the command
        cmd = [
            "python", "wp_find_one_link_per_site_v2.py",
            "--sites", input_path,
            "--keyword", keyword,
            "--out", output_name,
            "--mode", mode,
            "--threshold", str(threshold),
            "--require-external", require_external
        ]

        with st.spinner("Running script..."):
            subprocess.run(cmd)

        # If output file exists, show and download
        if os.path.exists(output_name):
            st.success(f"Finished! File saved as {output_name}")

            # Read and show as table
            try:
                df = pd.read_csv(output_name)
                st.dataframe(df)  # show table inside browser
            except Exception as e:
                st.warning(f"Could not read CSV: {e}")

            # Download button
            st.download_button("Download Results", open(output_name, "rb"), file_name=output_name)
        else:
            st.error("Output file not found.")
    else:
        st.warning("Please upload a file and enter a keyword.")
