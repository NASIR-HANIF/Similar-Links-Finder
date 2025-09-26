if st.button("Run Finder"):
    if uploaded_file is not None and keyword:
        input_path = os.path.join("temp_input.txt")
        with open(input_path, "wb") as f:
            f.write(uploaded_file.read())

        cmd = [
            "python", "wp_find_one_link_per_site_v2.py",
            "--sites", input_path,
            "--keyword", keyword,
            "--out", output_name,
            "--mode", mode,
            "--threshold", str(threshold),
            "--require-external", require_external
        ]

        # ⬅️ یہ لائن subprocess سے پہلے:
        st.write("Running command:", " ".join(cmd))

        with st.spinner("Running script..."):
            # ⬅️ subprocess.run کو result= … میں بدلیں
            result = subprocess.run(cmd, capture_output=True, text=True)

        # ⬅️ اور subprocess کے فوراً بعد یہ دو لائنیں لگائیں:
        st.text(result.stdout)
        st.text(result.stderr)

        if os.path.exists(output_name):
            st.success(f"Finished! File saved as {output_name}")
            try:
                df = pd.read_csv(output_name)
                st.dataframe(df)
            except Exception as e:
                st.warning(f"Could not read CSV: {e}")
            st.download_button("Download Results", open(output_name, "rb"), file_name=output_name)
        else:
            st.error("Output file not found.")
    else:
        st.warning("Please upload a file and enter a keyword.")


#  pip install streamlit pandas requests beautifulsoup4
#      (یا جو بھی requirements.txt میں ہیں، وہ سب ایک ساتھ: pip install -r requirements.txt)  

# https://similar-links-finder-pvjsn5fappdrdeiynegyrdf.streamlit.app/

# streamlit run app.py

# Local URL: http://localhost:8501
# Network URL: http://192.168.1.10:8501
