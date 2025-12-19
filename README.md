# fuck-wjx (WJX Auto-Filler)

English | [简体中文](./README_CN.md)

Inspired by https://github.com/Zemelee/wjx - don't forget to give that repo a star⭐

This project is a fun extension with new features, providing a GUI for configuring question distributions, weights, fill-in answers, etc., to automatically fill and batch-submit WenJuanXing (wjx.cn) surveys (a lifesaver for college students haha).

**Note: This project is for learning and testing purposes only. Ensure you have authorization to auto-submit the target survey. Avoid abuse or violating service terms. DO NOT pollute others' survey data!**

---

**Key Features**

- 💻 User-friendly GUI interface - zero barriers, no coding required, just know how to read
- ⭐ Local QR code decoding: upload a survey QR code image to automatically extract the link
- 😄 Free and unlimited - no need to beg friends or groups
- 🧑‍🤝‍🧑 Auto-parse question content and preset answers through configuration wizard, adjust option probabilities and ratios
- 🚀 Reduced waiting time after submission, faster survey filling
- 🎭 Full simulation mode: simulate real human behavior with typing delays and mouse movements for more natural submissions
- 🌍 Random IP submission: bypass IP restrictions、Captcher
- ⏸️ Stop anytime: gracefully stop execution at any time without losing progress
- 📁 Save survey configurations for reusing answer strategies on the same survey

<img width="600" height="505" alt="gui" src="https://github.com/user-attachments/assets/e9f71c9b-5222-4196-916c-df6eed5a743b" />


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

Before tweaking these controls make sure the survey has been parsed via the configuration wizard—you can revisit the wizard after each change.

- `Survey Link`
  - Paste the full WenJuanXing survey URL (example: `https://v.wjx.cn/vm/...`).
  - Alternatively use the "Upload QR Code" button and let the UI decode the link automatically.
  - The parsed questions refresh each time you change the link, so make sure the preview shows the expected questions.

- `Target Count`
  - The total number of submissions the bot will attempt.
  - Start with 3–5 entries to verify everything looks right; raise the number after confirming the workflow is stable.
  - The UI shows a countdown of how many samples remain, so you can pause early if needed.

- `Browser Count`
  - Controls how many Playwright browser instances run in parallel.
  - Higher values increase throughput but consume more CPU/RAM; typical home machines handle 2–5 safely.
  - If you plan long runs, monitor your system and reduce the count when usage spikes.

- `Distribution Method`
  - `Completely Random` picks answers uniformly from all available choices—good for dry runs.
  - `Custom Weight` lets you assign a weight to each option and the bot samples based on the resulting probability distribution.
  - Adjust sliders or enter percentages directly; the UI recalculates the preview ratio instantly.

- `Question List Area`
  - The left column lists all parsed questions and their detected types.
  - Select a question to open its configuration pane on the right, where you can edit answer presets, toggle required options, or lock/unlock selections.
  - For multi-select or matrix questions, define weights or fixed states per row/column so complex layouts behave predictably.

- `Select All` / Batch Operations
  - Use the header checkbox to select every question at once or clear the selection.
  - Once questions are selected, right-click or use the buttons below to run batch operations:
    - `Batch Delete` removes user-defined strategies without touching the original survey data.
    - `Batch Edit` applies the same distribution/answer strategy across the selected group.

- `Fill-in / Subjective Question Configuration`
  - For fill-in questions you can assign a single fixed answer or supply a list of candidates—each submission randomly picks one entry.
  - Subjective (long-text) questions accept text blocks or multiple presets; mix them to make answers appear less repetitive.
  - Use the preview to confirm line breaks and formatting before running the bot.

- `Auto Configure Survey`
  - Click this button anytime you change the survey link; the tool will visit the page, detect question types, and apply an initial strategy.
  - Some surveys require login or additional verification; if parsing fails, verify the link, cookies, or whether the survey is private.

- `Full Simulation Settings`
  - Enable "Full Simulation Mode" to mimic real human filling behavior with natural typing speed and mouse movements.
  - Set the total time duration (hours:minutes:seconds) for completing all submissions to distribute them evenly over time.
  - This mode significantly reduces detection risk but takes longer to complete.

- `Random IP Submission`
  - Check "Enable Random IP Submission" to bypass IP-based restrictions.
  - Useful when surveys have strict IP limits, but comes with additional costs.

- `Auto-Stop on Failures`
  - Enable "Auto-stop on too many failures" to automatically halt execution if consecutive failures exceed a threshold.
  - Prevents wasting resources when surveys become inaccessible or change their structure.

- `Start Execution`
  - After checking all inputs, hit "Start Execution" to let the bot auto-fill submissions according to your target count and strategy.
  - The log area on the right shows progress, success count, and any errors during runtime.
  - Use the "Stop" button to gracefully halt execution at any time - the system will wait for active threads to finish safely.

---

**Donate**

<img width="400" height="300" alt="payment" src="https://github.com/user-attachments/assets/62b6518f-97bb-4010-971a-3b89efb8359d" />

---

**How to Contribute**

Issues and PRs are welcome:
- Fix parsing stability
- Add compatibility for more question types/page structures
- Improve concurrency and error handling
- Speed up submission process
