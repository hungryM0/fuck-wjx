# fuck-wjx

English | [简体中文](./README_CN.md)

> Inspired by [Zemelee/wjx](https://github.com/Zemelee/wjx) - give that repo a star

A GUI-based automation tool for WenJuanXing (wjx.cn) surveys with customizable answer distribution and intelligent configuration.

> [!WARNING]
> **For learning and testing only.** Ensure you have authorization. **DO NOT pollute others' survey data!**

<img width="689" height="626" alt="gui" src="https://github.com/user-attachments/assets/dab85fed-1b28-4d45-8adf-37bb2770cf28" />

---

## Features

1. **Graphical Interface** - Complete all operations through a visual interface without writing code
2. **QR Code Recognition** - Upload survey QR code images for automatic link extraction
3. **Smart Configuration** - Automatically parse survey structure with customizable answer weights and probability distribution
4. **Random IP** - Support IP randomization to effectively bypass IP restrictions and captcha detection
5. **Graceful Termination** - Interrupt execution at any time without losing completed progress
6. **Configuration Reuse** - Import and export configuration files for repeated use

---

## Quick Start

> [!TIP]
> **Quick Setup:** Download the executable from [Release](https://github.com/hungryM0/fuck-wjx/releases/latest) for instant use without environment configuration.

### From Source

```bash
pip install -r requirements.txt
python fuck-wjx.py
```

**Requirements:** Windows 10/11 or Linux, Python 3.8+

---

## Usage

1. Enter survey link or upload QR code image
2. Click "Auto Configure Survey" to parse the survey structure
3. Adjust answer weight distribution through the configuration wizard
4. Set target submission count and concurrent browser instances
5. Click "Start Execution" and wait for task completion

---

## Key Settings

| Setting | What it does |
|---------|--------------|
| Target Count | Total number of submissions required (recommend testing with 3-5 first) |
| Browser Count | Concurrent browser instances for parallel execution (2-5 recommended for typical configurations) |
| Distribution | Answer selection strategy: completely random or custom-weighted distribution |
| Full Simulation | Simulate real user behavior (slower but more secure) |
| Random IP | Use random IP to bypass restrictions (Note: may incur additional costs) |

---

## Community

For questions or technical support, join our QQ Group:

<img width="256" alt="qq" src="https://github.com/user-attachments/assets/7f25caaa-b157-4185-acae-78882f56871d" />

---

## Contributing

Pull Requests are welcome. Areas for improvement include but are not limited to:
- Enhancing survey parsing stability and compatibility
- Adding support for additional question types
- Performance optimization and code refactoring

---

## Donate

<img width="250" alt="payment" src="assets/payment.png" />

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=hungryM0/fuck-wjx&type=date&legend=top-left)](https://www.star-history.com/#hungryM0/fuck-wjx&type=date&legend=top-left)
