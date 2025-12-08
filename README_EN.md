# fuck-wjx (WJX Auto-Filler)

English | [简体中文](./README.md)

Inspired by https://github.com/Zemelee/wjx - don't forget to give that repo a star⭐

This project is a fun extension with new features, providing a GUI for configuring question distributions, weights, fill-in answers, etc., to automatically fill and batch-submit WenJuanXing (wjx.cn) surveys (a lifesaver for college students haha).

**Note: This project is for learning and testing purposes only. Ensure you have authorization to auto-submit the target survey. Avoid abuse or violating service terms. DO NOT pollute others' survey data!**

<img width="600" height="505" alt="gui" src="https://github.com/user-attachments/assets/2d6f051b-112b-488f-b5ac-df52f90bffc9" />

---

**Key Features**

- 💻 User-friendly GUI interface - zero barriers, no coding required, just know how to read
- ⭐ Local QR code decoding: upload a survey QR code image to automatically extract the link
- 😄 Permanently free and unlimited - no need to beg friends or groups
- 🧑‍🤝‍🧑 Auto-parse question content and preset answers through configuration wizard, adjust option probabilities and ratios
- 🚀 Reduced waiting time after submission, faster survey filling
- 🌐 Simulates browser UA to bypass WeChat-only submission restrictions
- 📁 Save survey configurations for reusing answer strategies on the same survey

<img width="600" height="505" alt="QQ20251207-110703" src="https://github.com/user-attachments/assets/9e376c4f-43bc-4e97-b9b2-55f44d6d8c3f" />

---

**If You're Just a Survey-Filling Newbie**

✅ Download the exe release directly from [Release](https://github.com/hungryM0/fuck-wjx/releases/latest), double-click to run, ready to use out-of-the-box, no complex environment setup required!

---

A mysterious QQ group, feel free to ask questions there~

<img width="256" height="456" alt="qrcode_1764588750716" src="https://github.com/user-attachments/assets/7f25caaa-b157-4185-acae-78882f56871d" />

---

**Safety & Compliance**

⚠️ Only run this tool with authorization or for testing purposes. Auto-submitting surveys may violate service terms or laws - use at your own risk. DO NOT pollute others' survey data without authorization!

---

**Runtime Environment**

- Windows 10/11, Linux compatible
- Python 3.8+

**Python Dependencies**

- playwright
- numpy
- pyzbar
- Pillow
- requests
- packaging
- beautifulsoup4
- psutil

If you're a contributor downloading the source code, clone this repo and install dependencies with pip:

```bash
pip install -r requirements.txt
```

---

**How to Run from Source:**

```bash
python fuck-wjx.py
```
Or double-click `fuck-wjx.py` to open with Python

In the GUI that opens:
   - Enter the survey link, or click "Upload QR Code" to upload a QR code image for auto-detection
   - Click "Auto Configure Survey" to parse questions
   - Use the configuration wizard to add answer presets
   - Based on your needs, manually add more question configurations if necessary
   - Set target submission count and browser count, then click "Start Execution"

---

**Key Configuration Guide**

- `Survey Link`
  - Enter the full WenJuanXing survey page link (example: `https://v.wjx.cn/vm/...`).
  - Or click the "Upload QR Code" button to upload a survey QR code image - the program will auto-decode and fill in the link.

- `Target Count`
  - Total number of submissions to auto-fill and submit.
  - Higher numbers take longer; for testing, start with a smaller number (e.g., 3-5).

- `Browser Count`
  - Number of simultaneous browser instances (concurrency).
  - Higher values = faster overall speed, but more CPU/memory usage, potentially causing lag.
  - For typical home computers, 2-5 is recommended; adjust based on your specs.

- `Distribution Method`
  - `Completely Random`:
    - For multiple-choice questions, randomly select answers from all candidate options.
    - Suitable when you don't care about distribution and just want to "finish quickly".
  - `Custom Weight`:
    - Set a "weight" for each option; the program randomly selects answers based on weight ratios.
    - Example: Set A:50%, B:30%, C:20% to better simulate realistic survey data distribution.
    - In the GUI, adjust weights via sliders or input boxes with real-time percentage display.

- `Question List Area`
  - Left panel shows all parsed questions and question types from the current survey.
  - Click a question to view/edit its answer presets and weight configuration on the right.
  - For complex question types (multi-select, matrix), set weights or fixed selection status for each sub-option separately.

- `Select All` / Batch Operations
  - Checkbox in the top-left corner of the table header is the "Select All" button:
    - Check: Select all questions at once.
    - Uncheck: Deselect all questions.
  - After selecting multiple questions, use "Batch Delete", "Batch Edit", etc. from the bottom or right-click menu:
    - Batch Delete: Remove custom configurations for these questions (doesn't affect original survey questions).
    - Batch Edit: Apply the same distribution method or answer strategy to multiple questions simultaneously.

- `Fill-in / Subjective Question Configuration`
  - For fill-in questions, you can:
    - Set a fixed answer (every submission gets the same content), e.g., name, department, etc.
    - Or enter a "candidate answer list" - the program randomly picks one to fill in.
  - For subjective questions (long text), you can:
    - Configure a fixed text block.
    - Or preset multiple responses for the program to randomly select, avoiding identical answers for every submission.

- `Auto Configure Survey`
  - After clicking "Auto Configure Survey", the program will:
    - Visit the survey link and parse the page structure.
    - Auto-identify question types (single-choice, multi-choice, matrix, fill-in, etc.).
    - Provide default configurations for common question types (e.g., assign even weights to all options), which you can fine-tune.
  - If parsing fails, check if the survey link is correct, if login is required, or if access restrictions are set.

- `Start Execution`
  - After confirming all parameters are correct, click "Start Execution":
    - The program auto-fills and submits the survey according to the set "Target Count", "Browser Count", and question strategies.
    - The interface typically displays current progress, successful submission count, and error logs.
  - To stop during execution, close the program directly or use the "Stop" button provided in the interface (if implemented).

---

**How to Contribute**

Issues and PRs are welcome:
- Fix parsing stability
- Add compatibility for more question types/page structures
- Improve concurrency and error handling
- Speed up submission process
