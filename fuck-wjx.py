import logging
import math
import random
import re
import threading
import time
import traceback
import json
import os
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime
from threading import Thread
from typing import List, Optional, Union, Dict, Any

import numpy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.remote.webdriver import WebDriver
try:
    from selenium.webdriver.chrome.service import Service as ChromeService
except ImportError:
    ChromeService = None
from PIL import Image
from pyzbar.pyzbar import decode as pyzbar_decode

try:
    import requests
except ImportError:
    requests = None

try:
    from packaging import version
except ImportError:
    version = None

try:
    from webdriver_manager.chrome import ChromeDriverManager  # type: ignore[import]
except ImportError:
    ChromeDriverManager = None

# 版本号
__VERSION__ = "0.4"

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_BUFFER_CAPACITY = 2000
LOG_DIR_NAME = "logs"
CHROMEDRIVER_CACHE_DIR = "chromedriver_cache"

ORIGINAL_STDOUT = sys.stdout
ORIGINAL_STDERR = sys.stderr
ORIGINAL_EXCEPTHOOK = sys.excepthook
_chromedriver_lock = threading.Lock()
_cached_chromedriver_path: Optional[str] = None


class StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int, stream=None):
        self.logger = logger
        self.level = level
        self.stream = stream
        self._buffer = ""

    def write(self, message: str):
        if message is None:
            return
        text = str(message)
        self._buffer += text.replace("\r", "")
        if "\n" in self._buffer:
            parts = self._buffer.split("\n")
            self._buffer = parts.pop()
            for line in parts:
                self.logger.log(self.level, line)
        if self.stream:
            try:
                self.stream.write(message)
            except Exception:
                pass

    def flush(self):
        if self._buffer:
            self.logger.log(self.level, self._buffer)
            self._buffer = ""
        if self.stream:
            try:
                self.stream.flush()
            except Exception:
                pass


def _get_runtime_directory() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _get_chromedriver_cache_dir() -> str:
    cache_dir = os.path.join(_get_runtime_directory(), CHROMEDRIVER_CACHE_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _ensure_chromedriver_download() -> Optional[str]:
    if not ChromeDriverManager:
        logging.debug("webdriver_manager 未安装，依赖 PATH 中的 chromedriver")
        return None
    cache_dir = _get_chromedriver_cache_dir()
    try:
        driver_path = ChromeDriverManager(path=cache_dir).install()
        if driver_path and os.path.exists(driver_path):
            logging.info(f"Chromedriver 可用，已缓存: {driver_path}")
            return driver_path
    except Exception as exc:
        logging.warning(f"自动下载 ChromeDriver 失败: {exc}")
    return None


def resolve_chromedriver_path() -> Optional[str]:
    global _cached_chromedriver_path
    with _chromedriver_lock:
        if _cached_chromedriver_path and os.path.exists(_cached_chromedriver_path):
            return _cached_chromedriver_path
        driver_path = _ensure_chromedriver_download()
        if driver_path:
            _cached_chromedriver_path = driver_path
        return driver_path


def build_chrome_driver_kwargs() -> Dict[str, Any]:
    driver_path = resolve_chromedriver_path()
    if not driver_path:
        return {}
    if ChromeService:
        return {"service": ChromeService(executable_path=driver_path)}
    return {"executable_path": driver_path}


class LogBufferHandler(logging.Handler):
    def __init__(self, capacity: int = LOG_BUFFER_CAPACITY):
        super().__init__()
        self.capacity = capacity
        self.records: List[str] = []
        self.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        try:
            message = self.format(record)
            self.records.append(message)
            if self.capacity and len(self.records) > self.capacity:
                self.records.pop(0)
        except Exception:
            self.handleError(record)

    def get_records(self) -> List[str]:
        return list(self.records)


LOG_BUFFER_HANDLER = LogBufferHandler()
# 立即把缓冲处理器注册到根日志记录器，保证启动前的日志也能被收集
_root_logger = logging.getLogger()
if not any(isinstance(h, LogBufferHandler) for h in _root_logger.handlers):
    _root_logger.addHandler(LOG_BUFFER_HANDLER)
_root_logger.setLevel(logging.INFO)


url = ""

single_prob: List[Union[List[float], int]] = []
droplist_prob: List[Union[List[float], int]] = []
multiple_prob: List[List[float]] = []
matrix_prob: List[Union[List[float], int]] = []
scale_prob: List[Union[List[float], int]] = []
texts: List[List[str]] = []
texts_prob: List[List[float]] = []

target_num = 1
fail_threshold = 1
num_threads = 1
cur_num = 0
cur_fail = 0
lock = threading.Lock()
stop_event = threading.Event()

# GitHub 更新配置
GITHUB_OWNER = "hungryM0"
GITHUB_REPO = "fuck-wjx"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

# 可选：设置 GitHub Token 以避免 API 速率限制
# 优先从环境变量读取，如果没有则尝试从配置文件读取
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
if not GITHUB_TOKEN:
    # 尝试从同目录下的 .github_token 文件读取
    token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".github_token")
    if os.path.exists(token_file):
        try:
            with open(token_file, 'r', encoding='utf-8') as f:
                GITHUB_TOKEN = f.read().strip()
        except:
            pass


class UpdateManager:
    """GitHub 自动更新管理器"""
    
    @staticmethod
    def check_updates() -> Optional[Dict[str, Any]]:
        """
        检查 GitHub 上是否有新版本
        
        返回:
            如果有新版本，返回更新信息字典，包括:
            - has_update: 是否有更新
            - version: 新版本号
            - download_url: 下载地址
            - release_notes: 发布说明
            - file_name: 文件名
            
            如果无新版本或检查失败，返回 None
        """
        if not requests or not version:
            logging.warning("更新功能依赖 requests 和 packaging 模块")
            return None
        
        try:
            response = requests.get(GITHUB_API_URL, timeout=5)
            response.raise_for_status()
            latest_release = response.json()
            
            latest_version = latest_release['tag_name'].lstrip('v')
            current_version = __VERSION__
            
            # 比较版本号
            try:
                if version.parse(latest_version) <= version.parse(current_version):
                    return None
            except:
                logging.warning(f"版本比较失败: {latest_version} vs {current_version}")
                return None
            
            # 查找 .exe 文件资源（Release中的最新exe文件）
            download_url = None
            file_name = None
            for asset in latest_release.get('assets', []):
                if asset['name'].endswith('.exe'):
                    download_url = asset['browser_download_url']
                    file_name = asset['name']
                    break
            
            if not download_url:
                logging.warning("Release 中没有找到 .exe 文件")
                return None
            
            return {
                'has_update': True,
                'version': latest_version,
                'download_url': download_url,
                'release_notes': latest_release.get('body', ''),
                'file_name': file_name,
                'current_version': current_version
            }
            
        except requests.exceptions.Timeout:
            logging.warning("检查更新超时")
            return None
        except requests.exceptions.RequestException as e:
            logging.warning(f"检查更新失败: {e}")
            return None
        except Exception as e:
            logging.error(f"检查更新时发生错误: {e}")
            return None
    
    @staticmethod
    def download_update(download_url: str, file_name: str, progress_callback=None) -> Optional[str]:
        """
        下载更新文件
        
        参数:
            download_url: 下载链接
            file_name: 文件名（保留原始Release文件名）
            progress_callback: 进度回调函数 (downloaded, total)
            
        返回:
            下载的文件路径，失败返回 None
        """
        if not requests:
            logging.error("下载更新需要 requests 模块")
            return None
        
        try:
            logging.info(f"正在下载更新文件: {download_url}")
            response = requests.get(download_url, timeout=30, stream=True)
            response.raise_for_status()
            
            # 获取文件大小
            total_size = int(response.headers.get('content-length', 0))
            
            # 确定下载目录：如果是exe运行，使用exe所在目录；如果是py运行，使用py所在目录
            if getattr(sys, 'frozen', False):
                # 从打包的exe运行
                current_dir = os.path.dirname(sys.executable)
            else:
                # 从Python脚本运行
                current_dir = os.path.dirname(os.path.abspath(__file__))
            
            target_file = os.path.join(current_dir, file_name)
            temp_file = target_file + '.tmp'
            downloaded_size = 0
            
            logging.info(f"下载目标目录: {current_dir}")
            
            with open(temp_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded_size, total_size)
                        if total_size > 0:
                            progress = (downloaded_size / total_size) * 100
                            logging.debug(f"下载进度: {progress:.1f}%")
            
            # 移动临时文件到目标位置
            if os.path.exists(target_file):
                os.remove(target_file)
            os.rename(temp_file, target_file)

            logging.info(f"文件已成功下载到: {target_file}")

            UpdateManager.cleanup_old_executables(target_file)

            return target_file
            
        except Exception as e:
            logging.error(f"下载文件失败: {e}")
            # 清理临时文件
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                target_file = os.path.join(current_dir, file_name)
                temp_file = target_file + '.tmp'
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass
            return None
    
    @staticmethod
    def restart_application():
        """重启应用程序"""
        try:
            python_exe = sys.executable
            script_path = os.path.abspath(__file__)
            subprocess.Popen([python_exe, script_path])
            sys.exit(0)
        except Exception as e:
            logging.error(f"重启应用失败: {e}")

    @staticmethod
    def cleanup_old_executables(exclude_path: str):
        """删除目录下旧版本的exe文件（保留exclude_path本体）"""
        if not exclude_path:
            return
        directory = os.path.dirname(os.path.abspath(exclude_path))
        if not os.path.isdir(directory):
            return

        try:
            exclude_norm = os.path.normcase(os.path.abspath(exclude_path))
            for file in os.listdir(directory):
                if not file.lower().endswith('.exe'):
                    continue
                file_path = os.path.join(directory, file)
                if os.path.normcase(os.path.abspath(file_path)) == exclude_norm:
                    continue
                lower_name = file.lower()
                if 'fuck-wjx' not in lower_name and 'wjx' not in lower_name:
                    continue
                try:
                    os.remove(file_path)
                    logging.info(f"已删除旧版本: {file_path}")
                except Exception as exc:
                    logging.warning(f"无法删除旧版本 {file_path}: {exc}")
        except Exception as exc:
            logging.warning(f"清理旧版本时出错: {exc}")

    @staticmethod
    def schedule_running_executable_deletion(exclude_path: str):
        """调度在当前进程退出后删除正在运行的 exe 文件"""
        if not getattr(sys, "frozen", False):
            return
        current_executable = os.path.abspath(sys.executable)
        if not current_executable.lower().endswith('.exe'):
            return
        exclude_norm = os.path.normcase(os.path.abspath(exclude_path)) if exclude_path else ""
        if exclude_norm and os.path.normcase(current_executable) == exclude_norm:
            return

        safe_executable = current_executable.replace('%', '%%')
        script_content = (
            "@echo off\r\n"
            f"set \"target={safe_executable}\"\r\n"
            ":wait_loop\r\n"
            "if exist \"%target%\" (\r\n"
            "    del /f /q \"%target%\" >nul 2>&1\r\n"
            "    if exist \"%target%\" (\r\n"
            "        ping 127.0.0.1 -n 3 >nul\r\n"
            "        goto wait_loop\r\n"
            "    )\r\n"
            ")\r\n"
            "del /f /q \"%~f0\" >nul 2>&1\r\n"
        )

        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".bat") as script_file:
                script_file.write(script_content)
                script_path = script_file.name
            subprocess.Popen([
                "cmd.exe",
                "/c",
                script_path,
            ], creationflags=subprocess.CREATE_NO_WINDOW)
            logging.info(f"已调度删除旧版本执行文件: {current_executable}")
        except Exception as exc:
            logging.warning(f"调度删除旧版本失败: {exc}")


def setup_logging():
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    root_logger.setLevel(logging.INFO)
    if not any(isinstance(handler, LogBufferHandler) for handler in root_logger.handlers):
        root_logger.addHandler(LOG_BUFFER_HANDLER)
    if not getattr(setup_logging, "_streams_hooked", False):
        stdout_logger = StreamToLogger(root_logger, logging.INFO, stream=ORIGINAL_STDOUT)
        stderr_logger = StreamToLogger(root_logger, logging.ERROR, stream=ORIGINAL_STDERR)
        sys.stdout = stdout_logger
        sys.stderr = stderr_logger

        def _handle_unhandled_exception(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                if ORIGINAL_EXCEPTHOOK:
                    ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)
                return
            root_logger.error("未处理的异常", exc_info=(exc_type, exc_value, exc_traceback))
            if ORIGINAL_EXCEPTHOOK:
                ORIGINAL_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

        sys.excepthook = _handle_unhandled_exception
        setattr(setup_logging, "_streams_hooked", True)


def normalize_probabilities(values: List[float]) -> List[float]:
    if not values:
        raise ValueError("概率列表不能为空")
    total = sum(values)
    if total <= 0:
        raise ValueError("概率列表的和必须大于0")
    return [value / total for value in values]


@dataclass
class QuestionEntry:
    question_type: str
    probabilities: Union[List[float], int, None]
    texts: Optional[List[str]] = None
    rows: int = 1
    option_count: int = 0
    distribution_mode: str = "random"  # random, equal, custom
    custom_weights: Optional[List[float]] = None

    def summary(self) -> str:
        if self.question_type == "text":
            sample = " | ".join(self.texts or [])
            return f"答案: {sample or '默认空'}"
        if self.question_type == "matrix":
            mode_text = {"random": "完全随机", "custom": "自定义权重"}.get(self.distribution_mode, "完全随机")
            return f"{self.rows}行 × {self.option_count}列 - {mode_text}"
        if self.question_type == "multiple" and self.probabilities == -1:
            return f"{self.option_count}个选项 - 完全随机选择"
        if self.probabilities == -1:
            return f"{self.option_count}个选项 - 完全随机"
        mode_text = {"random": "完全随机", "custom": "自定义权重"}.get(self.distribution_mode, "完全随机")
        if self.question_type == "multiple" and self.custom_weights:
            weights_str = ",".join(f"{int(w)}%" for w in self.custom_weights)
            return f"{self.option_count}个选项 - 选中概率 {weights_str}"
        if self.distribution_mode == "custom" and self.custom_weights:
            weights_str = ":".join(str(int(w)) for w in self.custom_weights)
            return f"{self.option_count}个选项 - 权重 {weights_str}"
        return f"{self.option_count}个选项 - {mode_text}"


QUESTION_TYPE_LABELS = {
    "single": "单选题",
    "multiple": "多选题",
    "dropdown": "下拉题",
    "matrix": "矩阵题",
    "scale": "量表题",
    "text": "填空题",
}


def configure_probabilities(entries: List[QuestionEntry]):
    global single_prob, droplist_prob, multiple_prob, matrix_prob, scale_prob, texts, texts_prob
    single_prob = []
    droplist_prob = []
    multiple_prob = []
    matrix_prob = []
    scale_prob = []
    texts = []
    texts_prob = []

    for entry in entries:
        probs = entry.probabilities
        if entry.question_type == "single":
            single_prob.append(normalize_probabilities(probs) if isinstance(probs, list) else -1)
        elif entry.question_type == "dropdown":
            droplist_prob.append(normalize_probabilities(probs) if isinstance(probs, list) else -1)
        elif entry.question_type == "multiple":
            if not isinstance(probs, list):
                raise ValueError("多选题必须提供概率列表，数值范围0-100")
            multiple_prob.append([float(value) for value in probs])
        elif entry.question_type == "matrix":
            rows = max(1, entry.rows)
            if isinstance(probs, list):
                normalized = normalize_probabilities(probs)
                for _ in range(rows):
                    matrix_prob.append(list(normalized))
            else:
                for _ in range(rows):
                    matrix_prob.append(-1)
        elif entry.question_type == "scale":
            scale_prob.append(normalize_probabilities(probs) if isinstance(probs, list) else -1)
        elif entry.question_type == "text":
            values = entry.texts or []
            if not values:
                raise ValueError("填空题至少需要一个候选答案")
            if isinstance(probs, list):
                if len(probs) != len(values):
                    raise ValueError("填空题概率数量需与答案数量一致")
                normalized = normalize_probabilities(probs)
            else:
                normalized = normalize_probabilities([1.0] * len(values))
            texts.append(values)
            texts_prob.append(normalized)


def decode_qrcode(image_source: Union[str, Image.Image]) -> Optional[str]:
    """
    解码二维码图片,提取其中的链接
    
    参数:
        image_source: 图片文件路径(str)或PIL Image对象
    
    返回:
        str: 解码出的链接,如果解码失败返回None
    
    示例:
        >>> url = decode_qrcode("qrcode.png")
        >>> url = decode_qrcode(Image.open("qrcode.png"))
    """
    try:
        # 如果是文件路径,打开图片
        if isinstance(image_source, str):
            if not os.path.exists(image_source):
                raise FileNotFoundError(f"图片文件不存在: {image_source}")
            image = Image.open(image_source)
        else:
            image = image_source
        
        # 解码二维码
        decoded_objects = pyzbar_decode(image)
        
        if not decoded_objects:
            return None
        
        # 获取第一个二维码的数据
        qr_data = decoded_objects[0].data.decode('utf-8')
        
        # 验证是否为有效URL
        if qr_data.startswith(('http://', 'https://', 'www.')):
            return qr_data
        
        return qr_data
        
    except Exception as e:
        logging.error(f"二维码解码失败: {str(e)}")
        return None


def detect(driver: WebDriver) -> List[int]:
    question_counts_per_page: List[int] = []
    total_pages = len(driver.find_elements(By.XPATH, '//*[@id="divQuestion"]/fieldset'))
    for page_index in range(1, total_pages + 1):
        page_questions = driver.find_elements(By.XPATH, f'//*[@id="fieldset{page_index}"]/div')
        valid_question_count = 0
        for question_element in page_questions:
            topic_attr = question_element.get_attribute("topic")
            if topic_attr and topic_attr.isdigit():
                valid_question_count += 1
        question_counts_per_page.append(valid_question_count)
    return question_counts_per_page


def vacant(driver: WebDriver, current, index):
    answer_candidates = texts[index] if index < len(texts) else [""]
    selection_probabilities = texts_prob[index] if index < len(texts_prob) else [1.0]
    if not answer_candidates:
        answer_candidates = [""]
    if len(selection_probabilities) != len(answer_candidates):
        selection_probabilities = normalize_probabilities([1.0] * len(answer_candidates))
    selected_index = numpy.random.choice(a=numpy.arange(0, len(selection_probabilities)), p=selection_probabilities)
    driver.find_element(By.CSS_SELECTOR, f"#q{current}").send_keys(answer_candidates[selected_index])


def single(driver: WebDriver, current, index):
    options_xpath = f'//*[@id="div{current}"]/div[2]/div'
    option_elements = driver.find_elements(By.XPATH, options_xpath)
    probabilities = single_prob[index] if index < len(single_prob) else -1
    if probabilities == -1:
        selected_option = random.randint(1, len(option_elements))
    else:
        assert len(probabilities) == len(option_elements), f"第{current}题参数长度：{len(probabilities)},选项长度{len(option_elements)},不一致！"
        selected_option = numpy.random.choice(a=numpy.arange(1, len(option_elements) + 1), p=probabilities)
    driver.find_element(
        By.CSS_SELECTOR, f"#div{current} > div.ui-controlgroup > div:nth-child({selected_option})"
    ).click()


# 下拉框处理函数
def droplist(driver: WebDriver, current, index):
    # 先点击“请选择”
    driver.find_element(By.CSS_SELECTOR, f"#select2-q{current}-container").click()
    time.sleep(0.5)
    # 选项数量
    options = driver.find_elements(
        By.XPATH, f"//*[@id='select2-q{current}-results']/li"
    )
    if len(options) <= 1:
        return
    p = droplist_prob[index] if index < len(droplist_prob) else -1
    if p == -1:
        p = normalize_probabilities([1.0] * (len(options) - 1))
    r = numpy.random.choice(a=numpy.arange(1, len(options)), p=p)
    driver.find_element(
        By.XPATH, f"//*[@id='select2-q{current}-results']/li[{r + 1}]"
    ).click()


def multiple(driver: WebDriver, current, index):
    options_xpath = f'//*[@id="div{current}"]/div[2]/div'
    option_elements = driver.find_elements(By.XPATH, options_xpath)
    if not option_elements:
        return
    selection_probabilities = multiple_prob[index] if index < len(multiple_prob) else [50.0] * len(option_elements)
    
    if selection_probabilities == -1 or (isinstance(selection_probabilities, list) and len(selection_probabilities) == 1 and selection_probabilities[0] == -1):
        num_to_select = random.randint(1, max(1, len(option_elements)))
        selected_indices = random.sample(range(len(option_elements)), num_to_select)
        for option_idx in selected_indices:
            selector = f"#div{current} > div.ui-controlgroup > div:nth-child({option_idx + 1})"
            driver.find_element(By.CSS_SELECTOR, selector).click()
        return
    
    assert len(option_elements) == len(selection_probabilities), f"第{current}题概率值和选项值不一致"
    selection_mask = []
    while sum(selection_mask) == 0:
        selection_mask = [
            numpy.random.choice(a=numpy.arange(0, 2), p=[1 - (prob / 100), prob / 100])
            for prob in selection_probabilities
        ]
    for option_idx, is_selected in enumerate(selection_mask):
        if is_selected == 1:
            selector = f"#div{current} > div.ui-controlgroup > div:nth-child({option_idx + 1})"
            driver.find_element(By.CSS_SELECTOR, selector).click()


def matrix(driver: WebDriver, current, index):
    rows_xpath = f'//*[@id="divRefTab{current}"]/tbody/tr'
    row_elements = driver.find_elements(By.XPATH, rows_xpath)
    matrix_row_count = sum(1 for row in row_elements if row.get_attribute("rowindex") is not None)
    
    columns_xpath = f'//*[@id="drv{current}_1"]/td'
    column_elements = driver.find_elements(By.XPATH, columns_xpath)
    if len(column_elements) <= 1:
        return index
    
    for row_index in range(1, matrix_row_count + 1):
        probabilities = matrix_prob[index] if index < len(matrix_prob) else -1
        index += 1
        if probabilities == -1:
            selected_column = random.randint(2, len(column_elements))
        else:
            selected_column = numpy.random.choice(a=numpy.arange(2, len(column_elements) + 1), p=probabilities)
        driver.find_element(
            By.CSS_SELECTOR, f"#drv{current}_{row_index} > td:nth-child({selected_column})"
        ).click()
    return index


def reorder(driver: WebDriver, current):
    items_xpath = f'//*[@id="div{current}"]/ul/li'
    order_items = driver.find_elements(By.XPATH, items_xpath)
    for position in range(1, len(order_items) + 1):
        selected_item = random.randint(position, len(order_items))
        driver.find_element(
            By.CSS_SELECTOR, f"#div{current} > ul > li:nth-child({selected_item})"
        ).click()
        time.sleep(0.4)


def scale(driver: WebDriver, current, index):
    scale_items_xpath = f'//*[@id="div{current}"]/div[2]/div/ul/li'
    scale_options = driver.find_elements(By.XPATH, scale_items_xpath)
    probabilities = scale_prob[index] if index < len(scale_prob) else -1
    if not scale_options:
        return
    if probabilities == -1:
        selected_index = random.randrange(len(scale_options))
    else:
        selected_index = numpy.random.choice(a=numpy.arange(0, len(scale_options)), p=probabilities)
    scale_options[selected_index].click()


def _set_slider_input_value(driver: WebDriver, current: int, value: int):
    try:
        slider_input = driver.find_element(By.CSS_SELECTOR, f"#q{current}")
    except NoSuchElementException:
        return
    script = (
        "const input = arguments[0];"
        "const target = String(arguments[1]);"
        "input.value = target;"
        "['input','change'].forEach(evt => input.dispatchEvent(new Event(evt, { bubbles: true })));"
    )
    try:
        driver.execute_script(script, slider_input, value)
    except Exception:
        pass


def _click_slider_track(driver: WebDriver, container, ratio: float) -> bool:
    xpath_candidates = [
        ".//div[contains(@class,'wjx-slider') or contains(@class,'slider-track') or contains(@class,'range-slider') or contains(@class,'ui-slider') or contains(@class,'scale-slider') or contains(@class,'slider-container')]",
        ".//div[@role='slider']",
    ]
    for xpath in xpath_candidates:
        tracks = container.find_elements(By.XPATH, xpath)
        for track in tracks:
            width = track.size.get("width") or 0
            height = track.size.get("height") or 0
            if width <= 0 or height <= 0:
                continue
            offset_x = int(width * ratio)
            offset_x = max(5, min(offset_x, width - 5))
            offset_y = max(1, height // 2)
            try:
                ActionChains(driver).move_to_element_with_offset(track, offset_x, offset_y).click().perform()
                return True
            except Exception:
                continue
    return False


def slider_question(driver: WebDriver, current: int, score: int):
    ratio = max(0.0, min(score / 100.0, 1.0))
    try:
        container = driver.find_element(By.CSS_SELECTOR, f"#div{current}")
    except NoSuchElementException:
        container = None
    if container:
        _click_slider_track(driver, container, ratio)
    _set_slider_input_value(driver, current, score)


def brush(driver: WebDriver):
    questions_per_page = detect(driver)
    single_question_index = 0
    vacant_question_index = 0
    droplist_question_index = 0
    multiple_question_index = 0
    matrix_question_index = 0
    scale_question_index = 0
    current_question_number = 0
    
    for questions_count in questions_per_page:
        for _ in range(1, questions_count + 1):
            current_question_number += 1
            question_type = driver.find_element(
                By.CSS_SELECTOR, f"#div{current_question_number}"
            ).get_attribute("type")
            
            if question_type in ("1", "2"):
                vacant(driver, current_question_number, vacant_question_index)
                vacant_question_index += 1
            elif question_type == "3":
                single(driver, current_question_number, single_question_index)
                single_question_index += 1
            elif question_type == "4":
                multiple(driver, current_question_number, multiple_question_index)
                multiple_question_index += 1
            elif question_type == "5":
                scale(driver, current_question_number, scale_question_index)
                scale_question_index += 1
            elif question_type == "6":
                matrix_question_index = matrix(driver, current_question_number, matrix_question_index)
            elif question_type == "7":
                droplist(driver, current_question_number, droplist_question_index)
                droplist_question_index += 1
            elif question_type == "8":
                slider_score = random.randint(1, 100)
                slider_question(driver, current_question_number, slider_score)
            elif question_type == "11":
                reorder(driver, current_question_number)
            else:
                print(f"第{current_question_number}题为不支持题型！")
        time.sleep(0.5)
        try:
            driver.find_element(By.CSS_SELECTOR, "#divNext").click()
            time.sleep(0.5)
        except:
            driver.find_element(By.XPATH, '//*[@id="ctlNext"]').click()
    submit(driver)


def submit(driver: WebDriver):
    time.sleep(1)
    try:
        driver.find_element(By.XPATH, '//*[@id="layui-layer1"]/div[3]/a').click()
        time.sleep(1)
    except:
        pass
    try:
        driver.find_element(By.XPATH, '//*[@id="SM_BTN_1"]').click()
        time.sleep(0.5)
    except:
        pass
    try:
        slider_text_element = driver.find_element(By.XPATH, '//*[@id="nc_1__scale_text"]/span')
        slider_handle = driver.find_element(By.XPATH, '//*[@id="nc_1_n1z"]')
        if str(slider_text_element.text).startswith("请按住滑块"):
            slider_width = slider_text_element.size.get("width") or 0
            ActionChains(driver).drag_and_drop_by_offset(
                slider_handle, int(slider_width), 0
            ).perform()
    except:
        pass


def run(window_x_pos, window_y_pos, stop_signal: threading.Event, gui_instance=None):
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    
    global cur_num, cur_fail
    while True:
        # 使用锁检查并响应停止/完成条件，避免竞态导致超额提交
        with lock:
            if stop_signal.is_set() or (target_num > 0 and cur_num >= target_num):
                break
        driver = None
        try:
            driver_kwargs = build_chrome_driver_kwargs()
            driver = webdriver.Chrome(**driver_kwargs, options=chrome_options)
            if gui_instance and hasattr(gui_instance, 'active_drivers'):
                gui_instance.active_drivers.append(driver)
            driver.set_window_size(550, 650)
            driver.set_window_position(x=window_x_pos, y=window_y_pos)
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
                },
            )
            driver.get(url)
            initial_url = driver.current_url
            brush(driver)
            time.sleep(0.5)
            final_url = driver.current_url
            if initial_url != final_url:
                with lock:
                    # 再次检查，避免并发导致超额
                    if target_num <= 0 or cur_num < target_num:
                        cur_num += 1
                        print(
                            f"已填写{cur_num}份 - 失败{cur_fail}次 - {time.strftime('%H:%M:%S', time.localtime(time.time()))} "
                        )
                        # 达到目标后通知其他线程停止
                        if target_num > 0 and cur_num >= target_num:
                            stop_signal.set()
                    else:
                        # 已经达到或超过目标，设置停止并退出本线程
                        stop_signal.set()
                        break
        except:
            traceback.print_exc()
            with lock:
                cur_fail += 1
                print(f"已失败{cur_fail}次,失败超过{int(fail_threshold)}次将强制停止")
            if cur_fail >= fail_threshold:
                logging.critical("失败次数过多，程序将强制停止，请检查代码是否正确")
                stop_signal.set()
                break
        finally:
            if driver:
                try:
                    if gui_instance and hasattr(gui_instance, 'active_drivers') and driver in gui_instance.active_drivers:
                        gui_instance.active_drivers.remove(driver)
                    driver.quit()
                except:
                    pass


TYPE_OPTIONS = [
    ("single", "单选题"),
    ("multiple", "多选题"),
    ("dropdown", "下拉题"),
    ("matrix", "矩阵题"),
    ("scale", "量表题"),
    ("text", "填空题"),
]

LABEL_TO_TYPE = {label: value for value, label in TYPE_OPTIONS}


class SurveyGUI:

    def _save_logs_to_file(self):
        records = LOG_BUFFER_HANDLER.get_records()
        parent_window: tk.Misc = self.root
        log_window = getattr(self, "_log_window", None)
        if log_window and getattr(log_window, "winfo_exists", lambda: False)():
            parent_window = log_window
        if not records:
            self._log_popup_info("保存日志文件", "当前尚无日志可保存。", parent=parent_window)
            return

        logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), LOG_DIR_NAME)
        os.makedirs(logs_dir, exist_ok=True)
        file_name = datetime.now().strftime("log_%Y%m%d_%H%M%S.txt")
        file_path = os.path.join(logs_dir, file_name)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(records))
            logging.info(f"已保存日志文件: {file_path}")
            self._log_popup_info("保存日志文件", f"日志已保存到:\n{file_path}", parent=parent_window)
        except Exception as exc:
            logging.error(f"保存日志文件失败: {exc}")
            self._log_popup_error("保存日志文件失败", f"无法保存日志: {exc}", parent=parent_window)

    def _refresh_log_viewer(self):
        text_widget = getattr(self, "_log_text_widget", None)
        if not text_widget:
            return
        records = LOG_BUFFER_HANDLER.get_records()
        text_widget.configure(state="normal")
        text_widget.delete("1.0", tk.END)
        if records:
            text_widget.insert("1.0", "\n".join(records))
            text_widget.see(tk.END)
        text_widget.configure(state="disabled")

    def _log_popup_info(self, title: str, message: str, **kwargs):
        logging.info(f"[Popup Info] {title} | {message}")
        return messagebox.showinfo(title, message, **kwargs)

    def _log_popup_error(self, title: str, message: str, **kwargs):
        logging.error(f"[Popup Error] {title} | {message}")
        return messagebox.showerror(title, message, **kwargs)

    def _log_popup_confirm(self, title: str, message: str, **kwargs) -> bool:
        logging.info(f"[Popup Confirm] {title} | {message}")
        return messagebox.askyesno(title, message, **kwargs)

    def _on_root_focus(self, event=None):
        pass

    def _clear_logs_display(self):
        """清空日志显示"""
        # 清空日志缓冲区
        LOG_BUFFER_HANDLER.records.clear()
        # 清空 UI 显示
        if self._log_text_widget:
            self._log_text_widget.config(state="normal")
            self._log_text_widget.delete(1.0, tk.END)
            self._log_text_widget.config(state="disabled")

    def _schedule_log_refresh(self):
        """定期刷新日志显示"""
        if self._log_refresh_job:
            self.root.after_cancel(self._log_refresh_job)
        
        if self._log_text_widget:
            self._refresh_log_viewer()
        
        # 继续定期刷新
        self._log_refresh_job = self.root.after(500, self._schedule_log_refresh)

    def __init__(self):
        self.root = tk.Tk()
        # 在窗口标题中显示当前版本号
        try:
            ver = __VERSION__
        except NameError:
            ver = "0.0.0"
        self.root.title(f"问卷星速写 v{ver}")
        self.root.bind("<FocusIn>", self._on_root_focus)
        self.question_entries: List[QuestionEntry] = []
        self.runner_thread: Optional[Thread] = None
        self.worker_threads: List[Thread] = []
        self.active_drivers: List[WebDriver] = []  # 跟踪活跃的浏览器实例
        self.running = False
        self.status_job = None
        self.update_info = None  # 存储更新信息
        self.progress_value = 0  # 进度值 (0-100)
        self.total_submissions = 0  # 总提交数
        self.current_submissions = 0  # 当前提交数
        self._log_window: Optional[tk.Toplevel] = None
        self._log_text_widget: Optional[ScrolledText] = None
        self._log_refresh_job: Optional[str] = None
        self._paned_position_restored = False
        self._default_paned_position_applied = False
        self._config_changed = False  # 跟踪配置是否有改动
        self._initial_config: Dict[str, Any] = {}  # 存储初始配置以便比较
        self._wizard_history: List[int] = []
        self._last_parsed_url: Optional[str] = None
        self._last_questions_info: Optional[List[Dict[str, Any]]] = None
        self.url_var = tk.StringVar()
        self.target_var = tk.StringVar(value="")
        self.thread_var = tk.StringVar(value="2")
        self.preview_button: Optional[ttk.Button] = None
        self._build_ui()
        self._center_window()  # 窗口居中显示
        self._check_updates_on_startup()  # 启动时检查更新
        self._schedule_log_refresh()  # 启动日志刷新

    def _build_ui(self):
        self.root.geometry("950x750")
        self.root.resizable(True, True)

        # 创建菜单栏
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="帮助", menu=help_menu)
        help_menu.add_command(label="检查更新", command=self.check_for_updates)
        help_menu.add_separator()
        help_menu.add_command(label="关于", command=self.show_about)

        # 创建主容器，使用 PanedWindow 分左右两部分
        self.main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 左侧：配置区域（可滚动）
        config_container = ttk.Frame(self.main_paned)
        self.main_paned.add(config_container, weight=1)
        
        # 创建 Canvas 和 Scrollbar 用于整页滚动
        main_canvas = tk.Canvas(config_container, highlightthickness=0, bg="#f0f0f0")
        main_scrollbar = ttk.Scrollbar(config_container, orient="vertical", command=main_canvas.yview)
        
        # 创建可滚动的内容框架
        self.scrollable_content = ttk.Frame(main_canvas)
        
        # 创建窗口
        canvas_frame = main_canvas.create_window((0, 0), window=self.scrollable_content, anchor="nw")
        
        # 配置 scrollregion - 立即设置，避免空白
        def _update_scrollregion():
            self.scrollable_content.update_idletasks()
            main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        
        self.scrollable_content.bind("<Configure>", lambda e: _update_scrollregion())
        
        # 当 Canvas 大小改变时，调整内容宽度
        def _on_canvas_configure(event):
            if event.width > 1:
                main_canvas.itemconfig(canvas_frame, width=event.width)
        
        main_canvas.bind("<Configure>", _on_canvas_configure)
        main_canvas.configure(yscrollcommand=main_scrollbar.set)
        
        # 布局 Canvas 和 Scrollbar
        main_canvas.pack(side="left", fill="both", expand=True)
        main_scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮事件（仅在鼠标在主窗口时）
        def _on_mousewheel(event):
            # 阻止向上滚动超出顶部
            if event.delta > 0 and main_canvas.yview()[0] <= 0:
                return
            main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        def _bind_mousewheel(event):
            main_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(event):
            main_canvas.unbind_all("<MouseWheel>")

        # 仅在配置区域获得焦点时启用滚轮
        main_canvas.bind("<Enter>", _bind_mousewheel)
        main_canvas.bind("<Leave>", _unbind_mousewheel)
        
        # 保存引用以便后续使用
        self.main_canvas = main_canvas
        self.main_scrollbar = main_scrollbar

        # 右侧：日志区域
        log_container = ttk.LabelFrame(self.main_paned, text="📋 执行日志", padding=5)
        self.main_paned.add(log_container, weight=2)
        
        # 创建日志显示区域（ScrolledText）
        self._log_text_widget = ScrolledText(log_container, wrap=tk.NONE, state="disabled")
        self._log_text_widget.pack(fill=tk.BOTH, expand=True)
        
        # 日志按钮区域
        log_button_frame = ttk.Frame(log_container)
        log_button_frame.pack(fill=tk.X, padx=0, pady=(5, 0))
        
        ttk.Button(log_button_frame, text="保存日志文件", command=self._save_logs_to_file).pack(side=tk.RIGHT, padx=2)
        ttk.Button(log_button_frame, text="清空日志", command=self._clear_logs_display).pack(side=tk.RIGHT, padx=2)

        # 问卷链接输入区域
        step1_frame = ttk.LabelFrame(self.scrollable_content, text="🔗 问卷链接", padding=10)
        step1_frame.pack(fill=tk.X, padx=10, pady=5)

        link_frame = ttk.Frame(step1_frame)
        link_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(link_frame, text="问卷链接：").pack(side=tk.LEFT, padx=(0, 5))
        self.url_var.trace("w", lambda *args: self._mark_config_changed())
        url_entry = ttk.Entry(link_frame, textvariable=self.url_var, width=50)
        url_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)

        qr_frame = ttk.Frame(step1_frame)
        qr_frame.pack(fill=tk.X, pady=(0, 5))
        qr_upload_button = ttk.Button(
            qr_frame,
            text="📂上传问卷二维码图片",
            command=self.upload_qrcode,
            width=24,
            style="Accent.TButton"
        )
        qr_upload_button.pack(side=tk.LEFT, padx=5, pady=5, ipady=2)

        # 配置题目区域
        step2_frame = ttk.LabelFrame(self.scrollable_content, text="⚙️ 配置题目", padding=10)
        step2_frame.pack(fill=tk.X, padx=10, pady=5)

        auto_config_frame = ttk.Frame(step2_frame)
        auto_config_frame.pack(fill=tk.X, pady=(0, 5))

        button_row = ttk.Frame(auto_config_frame)
        button_row.pack(fill=tk.X)
        self.preview_button = ttk.Button(
            button_row,
            text="⚡ 自动配置问卷",
            command=self.preview_survey,
            style="Accent.TButton"
        )
        self.preview_button.pack(side=tk.LEFT, padx=5)

        auto_hint_frame = ttk.Frame(step2_frame)
        auto_hint_frame.pack(fill=tk.X, pady=(0, 10))
        self._auto_hint_label = ttk.Label(
            auto_hint_frame,
            text="← 自动解析问卷并开始引导配置答案，简单快捷",
            foreground="#01A034",
            font=("TkDefaultFont", 9),
            wraplength=350,
            justify="left"
        )
        self._auto_hint_label.pack(anchor="w", fill=tk.X)
        auto_hint_frame.bind("<Configure>", lambda e: self._auto_hint_label.configure(wraplength=max(100, e.width - 20)))

        # 执行设置区域（放在配置题目下方）
        step3_frame = ttk.LabelFrame(self.scrollable_content, text="⚙️ 执行设置", padding=10)
        step3_frame.pack(fill=tk.X, padx=10, pady=5)

        settings_grid = ttk.Frame(step3_frame)
        settings_grid.pack(fill=tk.X)
        settings_grid.columnconfigure(1, weight=1)
        
        ttk.Label(settings_grid, text="目标份数：").grid(row=0, column=0, sticky="w", padx=5)
        self.target_var.trace("w", lambda *args: self._mark_config_changed())
        ttk.Entry(settings_grid, textvariable=self.target_var, width=10).grid(
            row=0, column=1, sticky="w", padx=5
        )

        ttk.Label(
            settings_grid,
            text="线程数（浏览器并发数量）：",
            wraplength=220,
            justify="left"
        ).grid(row=1, column=0, sticky="w", padx=5, pady=(8, 0))
        self.thread_var.trace("w", lambda *args: self._mark_config_changed())
        
        def adjust_thread_count(delta: int) -> None:
            try:
                current = int(self.thread_var.get())
            except ValueError:
                current = 1
            new_value = max(1, current + delta)
            self.thread_var.set(str(new_value))
            self._mark_config_changed()

        thread_control_frame = ttk.Frame(settings_grid)
        thread_control_frame.grid(row=1, column=1, sticky="w", padx=5, pady=(8, 0))
        ttk.Button(
            thread_control_frame,
            text="−",
            width=2,
            command=lambda: adjust_thread_count(-1)
        ).grid(row=0, column=0, padx=(0, 2))
        ttk.Entry(thread_control_frame, textvariable=self.thread_var, width=5).grid(row=0, column=1, padx=2)
        ttk.Button(
            thread_control_frame,
            text="＋",
            width=2,
            command=lambda: adjust_thread_count(1)
        ).grid(row=0, column=2, padx=(2, 0))

        # 高级选项：手动配置（始终显示）
        self.manual_config_frame = ttk.LabelFrame(self.scrollable_content, text="🔧 高级选项", padding=10)
        self.manual_config_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # 按钮区域（放在这个 LabelFrame 中）
        btn_frame = ttk.Frame(self.manual_config_frame)
        btn_frame.pack(fill=tk.X, pady=5)
        
        # 全选复选框
        self.select_all_var = tk.BooleanVar(value=False)
        self.select_all_check = ttk.Checkbutton(
            btn_frame, 
            text="全选",
            variable=self.select_all_var,
            command=self.toggle_select_all
        )
        self.select_all_check.grid(row=0, column=0, padx=5)
        
        ttk.Button(btn_frame, text="手动添加配置", command=self.add_question_dialog).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(btn_frame, text="编辑选中", command=self.edit_question).grid(
            row=0, column=2, padx=5
        )
        ttk.Button(btn_frame, text="删除选中", command=self.remove_question).grid(
            row=0, column=3, padx=5
        )
        
        # 提示信息（放在按钮下，避免被树状控件遮挡）
        info_frame = ttk.Frame(self.manual_config_frame)
        info_frame.pack(fill=tk.X, padx=5, pady=(0, 6))
        self._manual_hint_label = ttk.Label(
            info_frame, 
            text="💡 提示：排序题和滑块题会自动随机处理，无需手动配置；点击\"添加配置\"弹出窗口设置题目参数",
            foreground="#0066cc",
            font=("TkDefaultFont", 9),
            wraplength=350,
            justify="left"
        )
        self._manual_hint_label.pack(anchor="w", fill=tk.X)
        info_frame.bind("<Configure>", lambda e: self._manual_hint_label.configure(wraplength=max(100, e.width - 20)))

        # 分隔符
        ttk.Separator(self.manual_config_frame, orient='horizontal').pack(fill=tk.X, pady=(0, 5))

        # 题目列表区域（放在最后）
        question_list_frame = ttk.LabelFrame(self.scrollable_content, text="📝 已配置的题目", padding=10)
        question_list_frame.pack(fill=tk.X, padx=10, pady=5)
        self.question_list_frame = question_list_frame
        
        tree_frame = ttk.Frame(question_list_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建带滚动条的Canvas（限制高度）
        canvas = tk.Canvas(tree_frame, highlightthickness=0, height=200)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.questions_canvas = canvas
        self.questions_frame = scrollable_frame
        self.question_items = []

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self._load_config()
        self.root.after(200, self._ensure_default_paned_position)
        
        # 执行按钮区域（固定在窗口底部，不参与滚动）
        action_frame = ttk.Frame(self.root, padding=10)
        action_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # 进度条区域（在上面）
        progress_frame = ttk.Frame(action_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(progress_frame, text="执行进度:", font=("TkDefaultFont", 9)).pack(side=tk.LEFT, padx=(0, 5))
        
        self.progress_bar = ttk.Progressbar(
            progress_frame, 
            mode='determinate', 
            maximum=100,
            length=300
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.progress_label = ttk.Label(progress_frame, text="0%", width=5, font=("TkDefaultFont", 9))
        self.progress_label.pack(side=tk.LEFT, padx=5)
        
        # 按钮行（在下面）
        button_frame = ttk.Frame(action_frame)
        button_frame.pack(fill=tk.X)
        
        self.start_button = ttk.Button(
            button_frame, 
            text="✔️ 开始执行", 
            command=self.start_run,
            style="Accent.TButton"
        )
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.stop_button = ttk.Button(button_frame, text="🚫 停止", command=self.stop_run, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="等待配置...")
        status_label = ttk.Label(button_frame, textvariable=self.status_var)
        status_label.pack(side=tk.LEFT, padx=10)

    def _ensure_default_paned_position(self):
        if self._paned_position_restored or self._default_paned_position_applied:
            return
        pane_width = self.main_paned.winfo_width() or self.root.winfo_width()
        if pane_width <= 0:
            self.root.after(100, self._ensure_default_paned_position)
            return
        desired = max(200, pane_width // 2)
        try:
            self.main_paned.sashpos(0, desired)
            self._default_paned_position_applied = True
        except Exception:
            pass


    def add_question_dialog(self):
        """弹出对话框来添加新的题目配置"""
        dialog = tk.Toplevel(self.root)
        dialog.title("添加题目配置")
        dialog.geometry("650x550")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 创建可滚动的内容区域
        main_canvas = tk.Canvas(dialog, highlightthickness=0)
        scrollbar = ttk.Scrollbar(dialog, orient="vertical", command=main_canvas.yview)
        main_frame = ttk.Frame(main_canvas, padding=15)
        
        main_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        
        main_canvas.create_window((0, 0), window=main_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮到对话框
        def _on_mousewheel(event):
            # 检查鼠标是否在canvas上方，如果是则处理滚轮事件
            if main_canvas.winfo_containing(event.x_root, event.y_root) == main_canvas:
                main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        dialog.bind("<MouseWheel>", _on_mousewheel)
        
        def _cleanup():
            dialog.unbind("<MouseWheel>")
            dialog.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", _cleanup)
        
        # ===== 题型选择 =====
        ttk.Label(main_frame, text="题型：", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w", pady=8, padx=(0, 10))
        question_type_var = tk.StringVar(value=TYPE_OPTIONS[0][1])
        question_type_combo = ttk.Combobox(
            main_frame,
            textvariable=question_type_var,
            state="readonly",
            values=[item[1] for item in TYPE_OPTIONS],
            width=30,
        )
        question_type_combo.grid(row=0, column=1, sticky="w", pady=8)
        
        # 创建一个容器用于动态内容
        dynamic_frame = ttk.Frame(main_frame)
        dynamic_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=10)
        main_frame.rowconfigure(1, weight=1)
        
        # 保存状态变量
        state: Dict[str, Any] = {
            'option_count_var': None,
            'matrix_rows_var': None,
            'distribution_var': None,
            'weights_var': None,
            'multiple_random_var': None,
            'answer_vars': None,
            'weight_frame': None,
            'current_sliders': None,
        }
        
        def refresh_dynamic_content(*args):
            """根据选择的题型刷新动态内容"""
            # 清空动态框
            for child in dynamic_frame.winfo_children():
                child.destroy()
            
            q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
            
            if q_type == "text":
                # ===== 填空题 =====
                ttk.Label(dynamic_frame, text="填空答案列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
                
                answer_frame = ttk.Frame(dynamic_frame)
                answer_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['answer_vars'] = []  # type: ignore
                
                def add_answer_field(initial_value=""):
                    row_frame = ttk.Frame(answer_frame)
                    row_frame.pack(fill=tk.X, pady=3, padx=5)
                    
                    ttk.Label(row_frame, text=f"答案{len(state['answer_vars'])+1}:", width=8).pack(side=tk.LEFT)  # type: ignore
                    
                    var = tk.StringVar(value=initial_value)
                    entry_widget = ttk.Entry(row_frame, textvariable=var, width=35)
                    entry_widget.pack(side=tk.LEFT, padx=5)
                    
                    def remove_field():
                        row_frame.destroy()
                        state['answer_vars'].remove(var)  # type: ignore
                        update_labels()
                    
                    if len(state['answer_vars']) > 0:  # type: ignore
                        ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)
                    
                    state['answer_vars'].append(var)  # type: ignore
                    return var
                
                def update_labels():
                    for i, child in enumerate(answer_frame.winfo_children()):
                        if child.winfo_children():
                            label = child.winfo_children()[0]
                            if isinstance(label, ttk.Label):
                                label.config(text=f"答案{i+1}:")
                
                add_answer_field("默认答案")
                
                add_btn_frame = ttk.Frame(dynamic_frame)
                add_btn_frame.pack(fill=tk.X, pady=(5, 0))
                ttk.Button(add_btn_frame, text="➕ 添加答案", command=lambda: add_answer_field()).pack(anchor="w")
                
            elif q_type == "multiple":
                # ===== 多选题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))
                        refresh_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="➖", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)
                ttk.Button(option_control_frame, text="➕", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 多选方式
                ttk.Label(dynamic_frame, text="多选方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['multiple_random_var'] = tk.BooleanVar(value=False)  # type: ignore
                ttk.Checkbutton(
                    dynamic_frame, 
                    text="完全随机选择若干项",
                    variable=state['multiple_random_var']  # type: ignore
                ).pack(anchor="w", pady=3, fill=tk.X)
                
                # 概率设置
                ttk.Label(dynamic_frame, text="选项选中概率（0-100%）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                sliders_frame = ttk.Frame(dynamic_frame)
                sliders_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_sliders():
                    for child in sliders_frame.winfo_children():
                        child.destroy()
                    state['current_sliders'] = []  # type: ignore
                    
                    try:
                        option_count = int(state['option_count_var'].get())  # type: ignore
                    except:
                        option_count = 4
                    
                    for i in range(option_count):
                        row_frame = ttk.Frame(sliders_frame)
                        row_frame.pack(fill=tk.X, pady=3, padx=(10, 10))
                        row_frame.columnconfigure(1, weight=1)
                        
                        var = tk.DoubleVar(value=50.0)
                        
                        label_text = ttk.Label(row_frame, text=f"选项 {i+1}:", width=8, anchor="w")
                        label_text.grid(row=0, column=0, sticky="w")
                        
                        slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                        slider.grid(row=0, column=1, sticky="ew", padx=5)
                        
                        percent_label = ttk.Label(row_frame, text="50%", width=6, anchor="e")
                        percent_label.grid(row=0, column=2, sticky="e")
                        
                        var.trace_add("write", lambda *args, l=percent_label, v=var: l.config(text=f"{int(v.get())}%"))
                        state['current_sliders'].append(var)  # type: ignore
                
                refresh_sliders()
                state['option_count_var'].trace_add("write", lambda *args: refresh_sliders())  # type: ignore
                
            elif q_type == "matrix":
                # ===== 矩阵题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数（列）：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")  # type: ignore
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))  # type: ignore
                        refresh_matrix_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="➖", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(option_control_frame, text="➕", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 矩阵行数
                matrix_row_frame = ttk.Frame(dynamic_frame)
                matrix_row_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(matrix_row_frame, text="矩阵行数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['matrix_rows_var'] = tk.StringVar(value="3")  # type: ignore
                
                def update_matrix_rows(delta):
                    try:
                        current = int(state['matrix_rows_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['matrix_rows_var'].set(str(new_count))  # type: ignore
                    except ValueError:
                        pass
                
                ttk.Button(matrix_row_frame, text="➖", width=3, command=lambda: update_matrix_rows(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(matrix_row_frame, textvariable=state['matrix_rows_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(matrix_row_frame, text="➕", width=3, command=lambda: update_matrix_rows(1)).pack(side=tk.LEFT, padx=2)
                
                # 分布方式
                ttk.Label(dynamic_frame, text="选择分布方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['distribution_var'] = tk.StringVar(value="random")  # type: ignore
                
                ttk.Radiobutton(dynamic_frame, text="完全随机（每次随机选择）", 
                              variable=state['distribution_var'], value="random",  # type: ignore
                              command=lambda: (state['weight_frame'].pack_forget() if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                ttk.Radiobutton(dynamic_frame, text="自定义权重（使用滑块设置）", 
                              variable=state['distribution_var'], value="custom",  # type: ignore
                              command=lambda: (state['weight_frame'].pack(fill=tk.BOTH, expand=True, pady=5) if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                
                # 权重滑块容器
                state['weight_frame'] = ttk.Frame(dynamic_frame)  # type: ignore
                
                ttk.Label(state['weight_frame'], text="选项权重（用:或,分隔，如 3:2:1）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 3), fill=tk.X)  # type: ignore
                
                state['weights_var'] = tk.StringVar(value="1:1:1:1")  # type: ignore
                ttk.Entry(state['weight_frame'], textvariable=state['weights_var'], width=40).pack(fill=tk.X, pady=3)  # type: ignore
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_matrix_sliders():
                    pass  # 矩阵题不需要动态刷新滑块
                
                state['option_count_var'].trace_add("write", lambda *args: refresh_matrix_sliders())  # type: ignore
                
            else:
                # ===== 单选、量表、下拉题 =====
                option_control_frame = ttk.Frame(dynamic_frame)
                option_control_frame.pack(fill=tk.X, pady=5)
                
                ttk.Label(option_control_frame, text="选项个数：", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
                
                state['option_count_var'] = tk.StringVar(value="4")  # type: ignore
                
                def update_option_count(delta):
                    try:
                        current = int(state['option_count_var'].get())  # type: ignore
                        new_count = max(1, current + delta)
                        state['option_count_var'].set(str(new_count))  # type: ignore
                        refresh_sliders()
                    except ValueError:
                        pass
                
                ttk.Button(option_control_frame, text="➖", width=3, command=lambda: update_option_count(-1)).pack(side=tk.LEFT, padx=2)
                ttk.Entry(option_control_frame, textvariable=state['option_count_var'], width=5).pack(side=tk.LEFT, padx=2)  # type: ignore
                ttk.Button(option_control_frame, text="➕", width=3, command=lambda: update_option_count(1)).pack(side=tk.LEFT, padx=2)
                
                # 分布方式
                ttk.Label(dynamic_frame, text="选择分布方式：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(10, 5), fill=tk.X)
                
                state['distribution_var'] = tk.StringVar(value="random")  # type: ignore
                
                ttk.Radiobutton(dynamic_frame, text="完全随机（每次随机选择）", 
                              variable=state['distribution_var'], value="random",  # type: ignore
                              command=lambda: (state['weight_frame'].pack_forget() if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                ttk.Radiobutton(dynamic_frame, text="自定义权重（使用滑块设置）", 
                              variable=state['distribution_var'], value="custom",  # type: ignore
                              command=lambda: (state['weight_frame'].pack(fill=tk.BOTH, expand=True, pady=5) if state['weight_frame'] else None)).pack(anchor="w", pady=3, fill=tk.X)  # type: ignore
                
                # 权重滑块容器
                state['weight_frame'] = ttk.Frame(dynamic_frame)  # type: ignore
                
                ttk.Label(state['weight_frame'], text="选项权重（0-10）：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 3), fill=tk.X)  # type: ignore
                
                sliders_frame = ttk.Frame(state['weight_frame'])  # type: ignore
                sliders_frame.pack(fill=tk.BOTH, expand=True, pady=5)
                
                state['current_sliders'] = []  # type: ignore
                
                def refresh_sliders():
                    for child in sliders_frame.winfo_children():
                        child.destroy()
                    state['current_sliders'] = []  # type: ignore
                    
                    try:
                        option_count = int(state['option_count_var'].get())  # type: ignore
                    except:
                        option_count = 4
                    
                    for i in range(option_count):
                        row_frame = ttk.Frame(sliders_frame)
                        row_frame.pack(fill=tk.X, pady=3, padx=(10, 10))
                        row_frame.columnconfigure(1, weight=1)
                        
                        var = tk.DoubleVar(value=1.0)
                        
                        label_text = ttk.Label(row_frame, text=f"选项 {i+1}:", width=8, anchor="w")
                        label_text.grid(row=0, column=0, sticky="w")
                        
                        slider = ttk.Scale(row_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                        slider.grid(row=0, column=1, sticky="ew", padx=5)
                        
                        weight_label = ttk.Label(row_frame, text="1.0", width=6, anchor="e")
                        weight_label.grid(row=0, column=2, sticky="e")
                        
                        def update_label(v=var, l=weight_label):
                            l.config(text=f"{v.get():.1f}")
                        
                        var.trace_add("write", lambda *args, v=var, l=weight_label: update_label(v, l))
                        state['current_sliders'].append(var)  # type: ignore
                
                refresh_sliders()
                state['option_count_var'].trace_add("write", lambda *args: refresh_sliders())  # type: ignore
        
        # 初始化动态内容
        question_type_combo.bind("<<ComboboxSelected>>", refresh_dynamic_content)
        refresh_dynamic_content()
        
        # ===== 按钮区域 =====
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=15, pady=(0, 15), side=tk.BOTTOM)
        
        def save_question():
            try:
                q_type = LABEL_TO_TYPE.get(question_type_var.get(), "single")
                option_count = 0
                distribution_mode = "equal"
                custom_weights = None
                probabilities = None
                texts_values = None
                rows = 1
                
                if q_type == "text":
                    raw = "||".join([var.get().strip() for var in state['answer_vars']]) if state['answer_vars'] else ""
                    if not raw:
                        self._log_popup_error("错误", "请填写至少一个答案")
                        return
                    parts = re.split(r"[|\n,]", raw)
                    texts_values = [item.strip() for item in parts if item.strip()]
                    if not texts_values:
                        self._log_popup_error("错误", "请填写至少一个答案")
                        return
                    option_count = len(texts_values)
                    probabilities = normalize_probabilities([1.0] * option_count)
                elif q_type == "multiple":
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    if option_count <= 0:
                        raise ValueError("选项个数必须为正整数")
                    if state['multiple_random_var'].get():  # type: ignore
                        probabilities = -1
                        distribution_mode = "random"
                    else:
                        if state['current_sliders']:  # type: ignore
                            custom_weights = [var.get() for var in state['current_sliders']]  # type: ignore
                        else:
                            custom_weights = [50.0] * option_count
                        probabilities = custom_weights
                        distribution_mode = "custom"
                elif q_type == "matrix":
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    rows = int(state['matrix_rows_var'].get())  # type: ignore
                    if option_count <= 0 or rows <= 0:
                        raise ValueError("选项数和行数必须为正整数")
                    distribution_mode = state['distribution_var'].get()  # type: ignore
                    if distribution_mode == "random":
                        probabilities = -1
                    elif distribution_mode == "equal":
                        probabilities = normalize_probabilities([1.0] * option_count)
                    else:
                        raw = state['weights_var'].get().strip()  # type: ignore
                        if not raw:
                            custom_weights = [1.0] * option_count
                        else:
                            parts = raw.replace("：", ":").replace("，", ",").replace(" ", "").split(":" if ":" in raw else ",")
                            custom_weights = [float(item.strip()) for item in parts if item.strip()]
                            if len(custom_weights) != option_count:
                                raise ValueError(f"权重数量({len(custom_weights)})与选项数({option_count})不匹配")
                        probabilities = normalize_probabilities(custom_weights)
                else:
                    option_count = int(state['option_count_var'].get())  # type: ignore
                    if option_count <= 0:
                        raise ValueError("选项个数必须为正整数")
                    distribution_mode = state['distribution_var'].get()  # type: ignore
                    if distribution_mode == "random":
                        probabilities = -1
                    elif distribution_mode == "equal":
                        probabilities = normalize_probabilities([1.0] * option_count)
                    else:
                        if state['current_sliders']:  # type: ignore
                            custom_weights = [var.get() for var in state['current_sliders']]  # type: ignore
                        else:
                            custom_weights = [1.0] * option_count
                        probabilities = normalize_probabilities(custom_weights)
                
                entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=probabilities,
                    texts=texts_values,
                    rows=rows,
                    option_count=option_count,
                    distribution_mode=distribution_mode,
                    custom_weights=custom_weights,
                )
                logging.info(f"[Action Log] Adding question type={q_type} options={option_count} mode={distribution_mode}")
                self.question_entries.append(entry)
                self._refresh_tree()
                _cleanup()
                logging.info(f"[Action Log] Question added successfully (total={len(self.question_entries)})")
            except ValueError as exc:
                self._log_popup_error("参数错误", str(exc))
        
        ttk.Button(button_frame, text="保存", command=save_question).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="取消", command=_cleanup).pack(side=tk.RIGHT, padx=5)


    def _get_selected_indices(self):
        return sorted([item['index'] for item in self.question_items if item['var'].get()])

    def toggle_select_all(self):
        """全选/取消全选所有题目"""
        select_all = self.select_all_var.get()
        for item in self.question_items:
            item['var'].set(select_all)

    def remove_question(self):
        selected_indices = self._get_selected_indices()
        if not selected_indices:
            logging.info("[Action Log] Remove question requested without selection")
            self._log_popup_info("提示", "请先勾选要删除的题目")
            return
        
        # 添加确认弹窗
        count = len(selected_indices)
        logging.info(f"[Action Log] Remove question requested for {count} items")
        confirm_msg = f"确定要删除选中的 {count} 道题目吗？\n\n此操作无法撤销！"
        if not self._log_popup_confirm("确认删除", confirm_msg, icon='warning'):
            logging.info("[Action Log] Remove question canceled by user")
            return
        
        for index in sorted(selected_indices, reverse=True):
            if 0 <= index < len(self.question_entries):
                self.question_entries.pop(index)
        logging.info(f"[Action Log] Removed {count} question(s)")
        
        self._refresh_tree()

    def edit_question(self):
        selected_indices = self._get_selected_indices()
        if not selected_indices:
            logging.info("[Action Log] Edit question requested without selection")
            self._log_popup_info("提示", "请先勾选要编辑的题目")
            return
        if len(selected_indices) > 1:
            logging.info("[Action Log] Edit question requested with multiple selections")
            self._log_popup_info("提示", "一次只能编辑一道题目")
            return
        index = selected_indices[0]
        if 0 <= index < len(self.question_entries):
            logging.info(f"[Action Log] Opening edit dialog for question #{index+1}")
            entry = self.question_entries[index]
            self._show_edit_dialog(entry, index)

    def _refresh_tree(self):
        # 清除所有旧项目
        for item in self.question_items:
            item['frame'].destroy()
        self.question_items.clear()
        
        # 为每个问题创建一行
        for idx, entry in enumerate(self.question_entries):
            # 创建一行的Frame
            row_frame = ttk.Frame(self.questions_frame)
            row_frame.pack(fill=tk.X, pady=2, padx=5)
            
            # 复选框（使用ttk样式）
            var = tk.BooleanVar(value=False)
            var.trace_add("write", lambda *args: self._update_select_all_state())
            cb = ttk.Checkbutton(row_frame, variable=var)
            cb.pack(side=tk.LEFT, padx=(0, 10))
            
            # 题型标签
            type_label = ttk.Label(row_frame, text=QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type), 
                                  width=12, anchor="w")
            type_label.pack(side=tk.LEFT, padx=(0, 10))
            
            # 配置信息标签
            detail_label = ttk.Label(row_frame, text=entry.summary(), anchor="w")
            detail_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            # 保存引用
            self.question_items.append({
                'frame': row_frame,
                'checkbox': cb,
                'var': var,
                'index': idx
            })
        
        # 标记配置有改动
        self._mark_config_changed()
        
        # 更新全选复选框状态
        self._update_select_all_state()

        self._safe_preview_button_config(text=self._get_preview_button_label())

    def _update_select_all_state(self):
        """根据单个复选框状态更新全选复选框"""
        if not self.question_items:
            self.select_all_var.set(False)
            return
        
        all_selected = all(item['var'].get() for item in self.question_items)
        self.select_all_var.set(all_selected)

    def _show_edit_dialog(self, entry, index):
        edit_win = tk.Toplevel(self.root)
        edit_win.title(f"编辑第 {index + 1} 题")
        edit_win.geometry("550x550")
        edit_win.transient(self.root)
        edit_win.grab_set()
        
        frame = ttk.Frame(edit_win, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=f"题型: {QUESTION_TYPE_LABELS.get(entry.question_type, entry.question_type)}", 
                 font=("TkDefaultFont", 10, "bold")).pack(pady=(0, 20))
        
        if entry.question_type == "text":
            ttk.Label(frame, text="填空答案列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
            
            answers_frame = ttk.Frame(frame)
            answers_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            canvas = tk.Canvas(answers_frame, height=200)
            scrollbar = ttk.Scrollbar(answers_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            scrollable_frame.bind(
                "<Configure>",
                lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
            )
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            answer_vars = []
            
            def add_answer_field(initial_value=""):
                row_frame = ttk.Frame(scrollable_frame)
                row_frame.pack(fill=tk.X, pady=5, padx=5)
                
                ttk.Label(row_frame, text=f"答案{len(answer_vars)+1}:", width=8).pack(side=tk.LEFT)
                
                var = tk.StringVar(value=initial_value)
                entry_widget = ttk.Entry(row_frame, textvariable=var, width=40)
                entry_widget.pack(side=tk.LEFT, padx=5)
                
                def remove_field():
                    row_frame.destroy()
                    answer_vars.remove(var)
                    update_labels()
                
                if len(answer_vars) > 0:
                    ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)
                
                answer_vars.append(var)
                return var
            
            def update_labels():
                for i, child in enumerate(scrollable_frame.winfo_children()):
                    label = child.winfo_children()[0]
                    if isinstance(label, ttk.Label):
                        label.config(text=f"答案{i+1}:")
            
            for answer in (entry.texts if entry.texts else ["默认答案"]):
                add_answer_field(answer)
            
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            add_btn_frame = ttk.Frame(frame)
            add_btn_frame.pack(fill=tk.X, pady=(5, 0))
            ttk.Button(add_btn_frame, text="➕ 添加答案", command=lambda: add_answer_field()).pack(anchor="w", fill=tk.X)
            
            def save_text():
                values = [var.get().strip() for var in answer_vars if var.get().strip()]
                if not values:
                    self._log_popup_error("错误", "请填写至少一个答案")
                    return
                entry.texts = values
                entry.probabilities = normalize_probabilities([1.0] * len(values))
                entry.option_count = len(values)
                self._refresh_tree()
                edit_win.destroy()
                logging.info(f"[Action Log] Saved text answers for question #{index+1}")
            
            save_btn = ttk.Button(frame, text="保存", command=save_text)
            save_btn.pack(pady=20, ipadx=20, ipady=5)
            
        elif entry.question_type == "multiple":
            ttk.Label(frame, text=f"多选题（{entry.option_count}个选项）").pack(anchor="w", pady=5, fill=tk.X)
            ttk.Label(frame, text="设置每个选项的选中概率（0-100%）：", 
                     foreground="gray").pack(anchor="w", pady=5, fill=tk.X)
            
            sliders = []
            slider_frame = ttk.Frame(frame)
            slider_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            canvas = tk.Canvas(slider_frame, height=250, highlightthickness=0)
            scrollbar = ttk.Scrollbar(slider_frame, orient="vertical", command=canvas.yview)
            scrollable_frame = ttk.Frame(canvas)
            
            canvas_win = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            
            def _on_scroll_config(event):
                canvas.configure(scrollregion=canvas.bbox("all"))
            scrollable_frame.bind("<Configure>", _on_scroll_config)
            
            def _on_canvas_config(event):
                canvas.itemconfigure(canvas_win, width=event.width)
            canvas.bind("<Configure>", _on_canvas_config)
            
            canvas.configure(yscrollcommand=scrollbar.set)
            
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            
            current_probs = entry.custom_weights if entry.custom_weights else [50.0] * entry.option_count
            # 获取选项文本（如果有的话）
            option_texts = entry.texts if entry.texts else []
            
            for i in range(entry.option_count):
                row_frame = ttk.Frame(scrollable_frame)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)
                
                # 显示选项文本（如果有的话）- 使用两行布局
                option_text = option_texts[i] if i < len(option_texts) and option_texts[i] else ""
                text_label = ttk.Label(row_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}", 
                                       anchor="w", wraplength=450)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
                
                # 第二行：滑块和百分比
                var = tk.DoubleVar(value=current_probs[i] if i < len(current_probs) else 50.0)
                slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))
                
                label = ttk.Label(row_frame, text=f"{int(var.get())}%", width=6, anchor="e")
                label.grid(row=1, column=2, sticky="e")
                
                var.trace_add("write", lambda *args, l=label, v=var: l.config(text=f"{int(v.get())}%"))
                sliders.append(var)
            
            def save_multiple():
                probs = [var.get() for var in sliders]
                entry.custom_weights = probs
                entry.probabilities = probs
                entry.distribution_mode = "custom"
                self._refresh_tree()
                edit_win.destroy()
                logging.info(f"[Action Log] Saved custom weights for question #{index+1}")
            
            save_btn = ttk.Button(frame, text="保存", command=save_multiple)
            save_btn.pack(pady=10, ipadx=20, ipady=5)
            
        else:
            ttk.Label(frame, text=f"选项数: {entry.option_count}").pack(anchor="w", pady=5, fill=tk.X)
            if entry.question_type == "matrix":
                ttk.Label(frame, text=f"矩阵行数: {entry.rows}").pack(anchor="w", pady=5, fill=tk.X)
            
            ttk.Label(frame, text="选择分布方式：").pack(anchor="w", pady=10, fill=tk.X)
            
            dist_var = tk.StringVar(value=entry.distribution_mode if entry.distribution_mode in ["random", "custom"] else "random")
            ttk.Radiobutton(frame, text="完全随机", variable=dist_var, value="random").pack(anchor="w", fill=tk.X)
            ttk.Radiobutton(frame, text="自定义权重", variable=dist_var, value="custom").pack(anchor="w", fill=tk.X)
            
            ttk.Label(frame, text="权重比例（用:or,分隔，如 3:2:1）：").pack(anchor="w", pady=10, fill=tk.X)
            weight_var = tk.StringVar(value=":".join(str(int(w)) for w in entry.custom_weights) if entry.custom_weights else "")
            weight_entry = ttk.Entry(frame, textvariable=weight_var, width=40)
            weight_entry.pack(fill=tk.X, pady=5)
            
            def save_other():
                mode = dist_var.get()
                if mode == "random":
                    entry.probabilities = -1
                    entry.custom_weights = None
                elif mode == "equal":
                    entry.probabilities = normalize_probabilities([1.0] * entry.option_count)
                    entry.custom_weights = [1.0] * entry.option_count
                else:
                    raw = weight_var.get().strip()
                    if not raw:
                        self._log_popup_error("错误", "请填写权重比例")
                        return
                    normalized = raw.replace("：", ":").replace("，", ",").replace(" ", "")
                    parts = normalized.split(":") if ":" in normalized else normalized.split(",")
                    try:
                        weights = [float(item.strip()) for item in parts if item.strip()]
                        if len(weights) != entry.option_count:
                            self._log_popup_error("错误", f"权重数量({len(weights)})与选项数({entry.option_count})不匹配")
                            return
                        entry.custom_weights = weights
                        entry.probabilities = normalize_probabilities(weights)
                    except:
                        self._log_popup_error("错误", "权重格式错误")
                        return
                
                entry.distribution_mode = mode
                self._refresh_tree()
                edit_win.destroy()
                logging.info(f"[Action Log] Saved distribution settings ({mode}) for question #{index+1}")
            
            save_btn = ttk.Button(frame, text="保存", command=save_other)
            save_btn.pack(pady=20, ipadx=20, ipady=5)



    def upload_qrcode(self):
        """上传二维码图片并解析链接"""
        file_path = filedialog.askopenfilename(
            title="选择问卷二维码图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")
            ]
        )
        
        if not file_path:
            return
        logging.info(f"[Action Log] QR code image selected: {file_path}")
        
        try:
            # 解码二维码
            url = decode_qrcode(file_path)
            
            if url:
                self.url_var.set(url)
                self._log_popup_info("成功", f"二维码解析成功！\n链接: {url}")
            else:
                self._log_popup_error("错误", "未能从图片中识别出二维码，请确认图片包含有效的二维码。")
        except Exception as e:
            logging.error(f"二维码解析失败: {str(e)}")
            self._log_popup_error("错误", f"二维码解析失败: {str(e)}")

    def preview_survey(self):
        url_value = self.url_var.get().strip()
        if not url_value:
            self._log_popup_error("错误", "请先填写问卷链接")
            return
        logging.info(f"[Action Log] Preview survey requested for URL: {url_value}")
        if self.question_entries and self._last_parsed_url == url_value and self._last_questions_info:
            self._safe_preview_button_config(state=tk.DISABLED, text="正在预览...")
            Thread(target=self._launch_preview_browser_session, args=(url_value,), daemon=True).start()
            return

        if self._last_parsed_url == url_value and self._last_questions_info:
            self._show_preview_window(deepcopy(self._last_questions_info))
            return

        self._safe_preview_button_config(state=tk.DISABLED, text="加载中...")
        
        # 创建进度窗口
        progress_win = tk.Toplevel(self.root)
        progress_win.title("正在加载问卷")
        progress_win.geometry("400x200")
        progress_win.resizable(False, False)
        progress_win.transient(self.root)
        
        # 居中显示进度窗口
        progress_win.update_idletasks()
        win_width = progress_win.winfo_width()
        win_height = progress_win.winfo_height()
        screen_width = progress_win.winfo_screenwidth()
        screen_height = progress_win.winfo_screenheight()
        
        try:
            import ctypes
            from ctypes.wintypes import RECT
            work_area = RECT()
            ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
            work_width = work_area.right - work_area.left
            work_height = work_area.bottom - work_area.top
            work_x = work_area.left
            work_y = work_area.top
            x = work_x + (work_width - win_width) // 2
            y = work_y + (work_height - win_height) // 2
        except:
            x = (screen_width - win_width) // 2
            y = (screen_height - win_height) // 2
        
        x = max(0, x)
        y = max(0, y)
        progress_win.geometry(f"+{x}+{y}")
        
        frame = ttk.Frame(progress_win, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="正在加载问卷...", font=('', 11, 'bold')).pack(pady=(0, 15))
        
        status_label = ttk.Label(frame, text="初始化浏览器...", foreground="gray")
        status_label.pack(pady=(0, 10))
        
        # 使用确定进度模式
        progress_bar = ttk.Progressbar(frame, mode='determinate', maximum=100, length=300)
        progress_bar.pack(fill=tk.X, pady=5)
        
        percentage_label = ttk.Label(frame, text="0%", font=('', 10, 'bold'))
        percentage_label.pack(pady=(5, 0))
        
        progress_win.update()
        
        preview_thread = Thread(target=self._parse_and_show_survey, args=(url_value, progress_win, status_label, progress_bar, percentage_label), daemon=True)
        preview_thread.start()

    def _parse_and_show_survey(self, survey_url, progress_win=None, status_label=None, progress_bar=None, percentage_label=None):
        driver = None
        try:
            # 更新进度函数
            def update_progress(percent, status_text):
                if progress_bar is not None:
                    self.root.after(0, lambda p=percent, pb=progress_bar: pb.config(value=p) if pb else None)
                if percentage_label is not None:
                    self.root.after(0, lambda p=percent, pl=percentage_label: pl.config(text=f"{int(p)}%") if pl else None)
                if status_label is not None:
                    self.root.after(0, lambda s=status_text, sl=status_label: sl.config(text=s) if sl else None)
            
            # 更新状态
            update_progress(5, "初始化浏览器...")
            
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            print(f"正在加载问卷: {survey_url}")
            driver_kwargs = build_chrome_driver_kwargs()
            driver = webdriver.Chrome(**driver_kwargs, options=chrome_options)
            
            update_progress(15, "加载问卷页面...")
            
            driver.get(survey_url)
            time.sleep(3)
            
            update_progress(30, "检测题目结构...")
            
            print("开始解析题目...")
            questions_info = []
            questions_per_page = detect(driver)
            total_questions = sum(questions_per_page)
            print(f"检测到 {len(questions_per_page)} 页，总题数: {total_questions}")
            current_question_num = 0
            
            for page_idx, questions_count in enumerate(questions_per_page, 1):
                print(f"正在解析第{page_idx}页，共{questions_count}题")
                
                for _ in range(questions_count):
                    current_question_num += 1
                    
                    # 计算进度百分比（30%~95%）
                    progress_percent = 30 + (current_question_num / max(total_questions, 1)) * 65
                    update_progress(progress_percent, f"正在解析第 {page_idx}/{len(questions_per_page)} 页 (已解析 {current_question_num}/{total_questions} 题)...")
                    
                    try:
                        question_div = driver.find_element(By.CSS_SELECTOR, f"#div{current_question_num}")
                        question_type = question_div.get_attribute("type")
                        
                        title_text = ""
                        try:
                            title_element = question_div.find_element(By.CSS_SELECTOR, ".topichtml")
                            title_text = title_element.text.strip()
                        except:
                            try:
                                title_element = question_div.find_element(By.CSS_SELECTOR, ".field-label")
                                full_text = title_element.text.strip()
                                lines = [line.strip() for line in full_text.split('\n') if line.strip()]
                                for line in lines:
                                    if not line.startswith('*') and not line.endswith('.'):
                                        title_text = line
                                        break
                            except:
                                pass
                        
                        if not title_text:
                            title_text = f"第{current_question_num}题"
                        
                        type_name = self._get_question_type_name(question_type)
                        option_count = 0
                        matrix_rows = 0
                        option_texts = []  # 存储选项文本
                        
                        if question_type in ("3", "4", "5", "7"):
                            if question_type == "7":
                                try:
                                    options = driver.find_elements(By.XPATH, f"//*[@id='q{current_question_num}']/option")
                                    option_count = max(0, len(options) - 1)
                                    # 提取下拉题选项文本
                                    option_texts = [opt.text.strip() for opt in options[1:]] if len(options) > 1 else []
                                except:
                                    option_count = 0
                                    option_texts = []
                            else:
                                try:
                                    options = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]/div[2]/div')
                                    option_count = len(options)
                                    # 提取单选/多选/量表题选项文本
                                    option_texts = [opt.text.strip() for opt in options]
                                except:
                                    try:
                                        options = driver.find_elements(By.XPATH, f'//*[@id="div{current_question_num}"]//div[@class="ui-radio"]')
                                        option_count = len(options)
                                        option_texts = [opt.text.strip() for opt in options]
                                    except:
                                        option_count = 0
                                        option_texts = []
                        elif question_type == "6":
                            try:
                                rows = driver.find_elements(By.XPATH, f'//*[@id="divRefTab{current_question_num}"]/tbody/tr')
                                matrix_rows = sum(1 for row in rows if row.get_attribute("rowindex") is not None)
                                columns = driver.find_elements(By.XPATH, f'//*[@id="drv{current_question_num}_1"]/td')
                                option_count = max(0, len(columns) - 1)
                                # 提取矩阵题列标题
                                option_texts = [col.text.strip() for col in columns[1:]] if len(columns) > 1 else []
                            except:
                                matrix_rows = 0
                                option_count = 0
                                option_texts = []
                        
                        questions_info.append({
                            "num": current_question_num,
                            "title": title_text,
                            "type": type_name,
                            "type_code": question_type,
                            "options": option_count,
                            "rows": matrix_rows,
                            "page": page_idx,
                            "option_texts": option_texts
                        })
                        print(f"  ✓ 第{current_question_num}题: {type_name} - {title_text[:30]}")
                    except Exception as e:
                        print(f"  ✗ 第{current_question_num}题解析失败: {e}")
                        traceback.print_exc()
                        questions_info.append({
                            "num": current_question_num,
                            "title": "[解析失败]",
                            "type": "未知",
                            "type_code": "0",
                            "options": 0,
                            "rows": 0,
                            "page": page_idx,
                            "option_texts": []
                        })
                
                if page_idx < len(questions_per_page):
                    try:
                        next_button = driver.find_element(By.CSS_SELECTOR, "#divNext")
                        next_button.click()
                        time.sleep(1.5)
                        print(f"已翻页到第{page_idx + 1}页")
                    except Exception as e:
                        print(f"翻页失败: {e}")
            
            print(f"解析完成，共{len(questions_info)}题")
            update_progress(100, "解析完成，正在显示结果...")
            time.sleep(0.5)
            if progress_win:
                self.root.after(0, lambda: progress_win.destroy())
            self._cache_parsed_survey(questions_info, survey_url)
            self.root.after(0, lambda: self._show_preview_window(questions_info))
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
            
        except Exception as e:
            error_msg = f"解析问卷失败: {str(e)}\n\n请检查:\n1. 问卷链接是否正确\n2. 网络连接是否正常\n3. Chrome浏览器是否安装正常"
            print(f"错误: {error_msg}")
            clean_error_msg = error_msg.replace("\n", " ")
            logging.error(f"[Action Log] Preview parsing failed: {clean_error_msg}")
            traceback.print_exc()
            if progress_win:
                self.root.after(0, lambda: progress_win.destroy())
            self.root.after(0, lambda: self._log_popup_error("错误", error_msg))
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

    def _cache_parsed_survey(self, questions_info: List[Dict[str, Any]], url: str):
        """缓存解析结果以便预览和配置向导复用"""
        self._last_parsed_url = url
        self._last_questions_info = deepcopy(questions_info)

    def _launch_preview_browser_session(self, url: str):
        driver = None
        try:
            configure_probabilities(self.question_entries)
        except ValueError as exc:
            self.root.after(0, lambda: self._log_popup_error("预览失败", str(exc)))
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))
            return

        try:
            chrome_options = webdriver.ChromeOptions()
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")

            driver_kwargs = build_chrome_driver_kwargs()
            driver = webdriver.Chrome(**driver_kwargs, options=chrome_options)
            driver.maximize_window()
            driver.get(url)

            logging.info(f"[Action Log] Launching preview session for {url}")
            if self._last_questions_info:
                self._fill_preview_answers(driver, self._last_questions_info)
            self.root.after(0, lambda: self._log_popup_info(
                "预览完成",
                "浏览器已自动填写一份，请在窗口中确认是否满意，提交/关闭请手动操作。"
            ))

        except Exception as exc:
            error_msg = f"预览演示失败: {exc}"
            logging.error(error_msg)
            traceback.print_exc()
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            self.root.after(0, lambda: self._log_popup_error("预览失败", error_msg))
        finally:
            self.root.after(0, lambda: self._safe_preview_button_config(state=tk.NORMAL, text=self._get_preview_button_label()))

    def _fill_preview_answers(self, driver: WebDriver, questions_info: List[Dict[str, Any]]) -> None:
        vacancy_idx = single_idx = droplist_idx = multiple_idx = matrix_idx = scale_idx = 0
        for q in questions_info:
            q_type = q.get("type_code")
            current = q.get("num")
            if not current or not q_type:
                continue
            try:
                if q_type in ("1", "2"):
                    vacant(driver, current, vacancy_idx)
                    vacancy_idx += 1
                elif q_type == "3":
                    single(driver, current, single_idx)
                    single_idx += 1
                elif q_type == "4":
                    multiple(driver, current, multiple_idx)
                    multiple_idx += 1
                elif q_type == "5":
                    scale(driver, current, scale_idx)
                    scale_idx += 1
                elif q_type == "6":
                    matrix_idx = matrix(driver, current, matrix_idx)
                elif q_type == "7":
                    droplist(driver, current, droplist_idx)
                    droplist_idx += 1
            except Exception as exc:
                logging.debug(f"预览题目 {current} ({q_type}) 填写失败: {exc}")

    def _safe_preview_button_config(self, **kwargs) -> None:
        if self.preview_button:
            self.preview_button.config(**kwargs)

    def _get_preview_button_label(self) -> str:
        return "预览问卷" if self.question_entries else "⚡ 自动配置问卷"

    def _get_question_type_name(self, type_code):
        type_map = {
            "1": "填空题(单行)",
            "2": "填空题(多行)",
            "3": "单选题",
            "4": "多选题",
            "5": "量表题",
            "6": "矩阵题",
            "7": "下拉题",
            "8": "滑块题",
            "11": "排序题"
        }
        return type_map.get(type_code, f"未知类型({type_code})")

    def _show_preview_window(self, questions_info):
        preview_win = tk.Toplevel(self.root)
        preview_win.title("问卷预览")
        preview_win.geometry("900x600")
        
        frame = ttk.Frame(preview_win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=f"问卷共 {len(questions_info)} 题", font=("TkDefaultFont", 11, "bold")).pack(pady=(0, 10))
        
        tree_frame = ttk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("num", "title", "type", "details", "page")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=20)
        tree.heading("num", text="题号")
        tree.heading("title", text="题目标题")
        tree.heading("type", text="题型")
        tree.heading("details", text="详情")
        tree.heading("page", text="页码")
        
        tree.column("num", width=50, anchor="center")
        tree.column("title", width=400, anchor="w")
        tree.column("type", width=120, anchor="center")
        tree.column("details", width=180, anchor="center")
        tree.column("page", width=60, anchor="center")
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        for q in questions_info:
            details = ""
            if q["type_code"] == "6":
                details = f"{q['rows']}行 × {q['options']}列"
            elif q["type_code"] in ("3", "4", "5", "7"):
                details = f"{q['options']}个选项"
            elif q["type_code"] in ("1", "2"):
                details = "文本输入"
            elif q["type_code"] == "8":
                details = "滑块(1-100)"
            elif q["type_code"] == "11":
                details = "拖拽排序"
            
            tree.insert("", "end", values=(
                q["num"],
                q["title"][:80] + "..." if len(q["title"]) > 80 else q["title"],
                q["type"],
                details,
                f"第{q['page']}页"
            ))
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(pady=(10, 0))
        
        wizard_btn = ttk.Button(btn_frame, text="开始配置题目", 
                               command=lambda: self._start_config_wizard(questions_info, preview_win))
        wizard_btn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(btn_frame, text="关闭", command=preview_win.destroy).pack(side=tk.LEFT, padx=5)

    def _start_config_wizard(self, questions_info, preview_win):
        preview_win.destroy()
        self.question_entries.clear()
        self._wizard_history = []
        self._show_wizard_for_question(questions_info, 0)

    def _show_wizard_for_question(self, questions_info, current_index):
        if current_index >= len(questions_info):
            self._refresh_tree()
            logging.info(f"[Action Log] Wizard finished with {len(self.question_entries)} configured questions")
            self._log_popup_info("完成", 
                              f"配置完成！\n\n"
                              f"已配置 {len(self.question_entries)} 道题目。\n"
                              f"可在下方题目列表中查看和编辑。")
            self._wizard_history.clear()
            return
        
        q = questions_info[current_index]
        type_code = q["type_code"]
        
        if type_code in ("8", "11"):
            self._show_wizard_for_question(questions_info, current_index + 1)
            return

        self._wizard_history.append(current_index)
        
        wizard_win = tk.Toplevel(self.root)
        wizard_win.title(f"配置向导 - 第 {current_index + 1}/{len(questions_info)} 题")
        wizard_win.geometry("800x600")
        wizard_win.minsize(700, 500)  # 设置最小尺寸，防止窗口过小
        wizard_win.transient(self.root)
        wizard_win.grab_set()

        # 创建可滚动的内容区域
        canvas = tk.Canvas(wizard_win, highlightthickness=0)
        scrollbar = ttk.Scrollbar(wizard_win, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=15)
        
        # 让 frame 的宽度跟随 Canvas 的宽度
        canvas_window = canvas.create_window((0, 0), window=frame, anchor="nw")
        
        def on_frame_configure(event=None):
            # 更新滚动区域
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def on_canvas_configure(event=None):
            # 让 frame 宽度适应 canvas 宽度
            canvas_width = canvas.winfo_width()
            if canvas_width > 1:  # 避免初始化时宽度为1
                canvas.itemconfig(canvas_window, width=canvas_width)
        
        frame.bind("<Configure>", on_frame_configure)
        canvas.bind("<Configure>", on_canvas_configure)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # 绑定鼠标滚轮到 Canvas
        def _on_wizard_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind_all("<MouseWheel>", _on_wizard_mousewheel)
        
        def _cleanup_mousewheel():
            canvas.unbind_all("<MouseWheel>")
            wizard_win.destroy()
        
        wizard_win.protocol("WM_DELETE_WINDOW", _cleanup_mousewheel)
        
        progress_text = f"进度: {current_index + 1} / {len(questions_info)}"
        ttk.Label(frame, text=progress_text, foreground="gray").pack(anchor="w", fill=tk.X)
        
        ttk.Label(frame, text=f"第 {q['num']} 题", 
                 font=("TkDefaultFont", 12, "bold")).pack(pady=(10, 5), anchor="w", fill=tk.X)
        
        # 使用 wraplength 确保题目标题完整显示并自动换行
        title_label = ttk.Label(frame, text=q["title"], 
                 font=("TkDefaultFont", 10), wraplength=700)
        title_label.pack(pady=(0, 10), anchor="w", fill=tk.X)
        
        # 当窗口大小变化时更新 wraplength - 使用 add="+" 避免覆盖原有的绑定
        def update_title_wraplength(event=None):
            new_width = frame.winfo_width() - 30  # 留一点边距
            if new_width > 100:  # 确保有效宽度
                title_label.configure(wraplength=new_width)
        frame.bind("<Configure>", update_title_wraplength, add="+")
        
        ttk.Label(frame, text=f"题型: {q['type']}", 
                 foreground="blue").pack(pady=(0, 20), anchor="w", fill=tk.X)
        
        config_frame = ttk.Frame(frame)
        config_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        def skip_question():
            wizard_win.destroy()
            self._show_wizard_for_question(questions_info, current_index + 1)
        
        if type_code in ("1", "2"):
            ttk.Label(config_frame, text="填空答案列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=5, fill=tk.X)
            
            answer_vars = []
            answers_inner_frame = ttk.Frame(config_frame)
            answers_inner_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            def add_answer_field(initial_value=""):
                row_frame = ttk.Frame(answers_inner_frame)
                row_frame.pack(fill=tk.X, pady=3, padx=5)
                
                ttk.Label(row_frame, text=f"答案{len(answer_vars)+1}:", width=8).pack(side=tk.LEFT)
                
                var = tk.StringVar(value=initial_value)
                entry_widget = ttk.Entry(row_frame, textvariable=var, width=35)
                entry_widget.pack(side=tk.LEFT, padx=5)
                
                def remove_field():
                    row_frame.destroy()
                    answer_vars.remove(var)
                    update_labels()
                
                if len(answer_vars) > 0:
                    ttk.Button(row_frame, text="✖", width=3, command=remove_field).pack(side=tk.LEFT)
                
                answer_vars.append(var)
                return var
            
            def update_labels():
                for i, child in enumerate(answers_inner_frame.winfo_children()):
                    if child.winfo_children():
                        label = child.winfo_children()[0]
                        if isinstance(label, ttk.Label):
                            label.config(text=f"答案{i+1}:")
            
            add_answer_field("")
            
            add_btn_frame = ttk.Frame(config_frame)
            add_btn_frame.pack(fill=tk.X, pady=(5, 0))
            ttk.Button(add_btn_frame, text="➕ 添加答案", command=lambda: add_answer_field()).pack(anchor="w")
            
            def save_and_next():
                values = [var.get().strip() for var in answer_vars if var.get().strip()]
                if not values:
                    self._log_popup_error("错误", "请填写至少一个答案")
                    return
                entry = QuestionEntry(
                    question_type="text",
                    probabilities=normalize_probabilities([1.0] * len(values)),
                    texts=values,
                    rows=1,
                    option_count=len(values),
                    distribution_mode="equal",
                    custom_weights=None
                )
                self.question_entries.append(entry)
                logging.info(f"[Action Log] Wizard added text question #{current_index+1}")
                wizard_win.destroy()
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        elif type_code == "4":
            ttk.Label(config_frame, text=f"多选题（共 {q['options']} 个选项）").pack(anchor="w", pady=5, fill=tk.X)
            ttk.Label(config_frame, text="拖动滑块设置每个选项的选中概率：", 
                     foreground="gray").pack(anchor="w", pady=5, fill=tk.X)
            
            sliders_frame = ttk.Frame(config_frame)
            sliders_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            sliders = []
            for i in range(q['options']):
                row_frame = ttk.Frame(sliders_frame)
                row_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                row_frame.columnconfigure(1, weight=1)

                # 显示选项文本（如果有的话）- 使用两行布局，第一行显示完整选项文本
                option_text = ""
                if i < len(q.get('option_texts', [])) and q['option_texts'][i]:
                    option_text = q['option_texts'][i]
                
                # 第一行：选项序号和完整文本
                text_label = ttk.Label(row_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}", 
                                       anchor="w", wraplength=500)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                # 第二行：滑块和百分比
                var = tk.DoubleVar(value=50.0)
                slider = ttk.Scale(row_frame, from_=0, to=100, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                label = ttk.Label(row_frame, text="50%", width=6, anchor="e")
                label.grid(row=1, column=2, sticky="e")

                var.trace_add("write", lambda *args, l=label, v=var: l.config(text=f"{int(v.get())}%"))
                sliders.append(var)
            
            def save_and_next():
                probs = [var.get() for var in sliders]
                # 保存选项文本以便编辑时显示
                option_texts_list = q.get('option_texts', [])
                entry = QuestionEntry(
                    question_type="multiple",
                    probabilities=probs,
                    texts=option_texts_list if option_texts_list else None,
                    rows=1,
                    option_count=q['options'],
                    distribution_mode="custom",
                    custom_weights=probs
                )
                self.question_entries.append(entry)
                wizard_win.destroy()
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        else:
            option_text = f"共 {q['options']} 个选项"
            if type_code == "6":
                option_text = f"{q['rows']} 行 × {q['options']} 列"
            ttk.Label(config_frame, text=option_text).pack(anchor="w", pady=10, fill=tk.X)
            
            # 对于矩阵题，显示列标题
            if type_code == "6" and q.get('option_texts'):
                ttk.Label(config_frame, text="列标题：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 0), fill=tk.X)
                options_info_text = " | ".join([f"{i+1}: {text[:20]}{'...' if len(text) > 20 else ''}" for i, text in enumerate(q['option_texts'])])
                ttk.Label(config_frame, text=options_info_text, foreground="gray", wraplength=700).pack(anchor="w", pady=(0, 10), fill=tk.X)
            
            # 对于单选题、量表题、下拉题，显示选项列表
            elif q.get('option_texts'):
                ttk.Label(config_frame, text="选项列表：", font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(5, 0), fill=tk.X)
                options_list_frame = ttk.Frame(config_frame)
                options_list_frame.pack(anchor="w", fill=tk.X, pady=(0, 10), padx=(20, 0))
                
                max_options_display = min(5, len(q['option_texts']))
                for i in range(max_options_display):
                    # 为选项文本添加 wraplength，防止长文本被截断
                    option_lbl = ttk.Label(options_list_frame, text=f"  • {q['option_texts'][i]}", 
                                          foreground="gray", wraplength=650)
                    option_lbl.pack(anchor="w", fill=tk.X)
                
                if len(q['option_texts']) > 5:
                    ttk.Label(options_list_frame, text=f"  ... 共 {len(q['option_texts'])} 个选项", foreground="gray").pack(anchor="w", fill=tk.X)
            
            ttk.Label(config_frame, text="选择分布方式：").pack(anchor="w", pady=10, fill=tk.X)
            
            dist_var = tk.StringVar(value="random")
            
            # 权重输入区域（初始隐藏）
            weight_frame = ttk.Frame(config_frame)
            
            ttk.Radiobutton(config_frame, text="完全随机（每次随机选择）", 
                          variable=dist_var, value="random",
                          command=lambda: weight_frame.pack_forget()).pack(anchor="w", pady=5, fill=tk.X)
            ttk.Radiobutton(config_frame, text="自定义权重（使用滑块设置）", 
                          variable=dist_var, value="custom",
                          command=lambda: weight_frame.pack(fill=tk.BOTH, expand=True, pady=10)).pack(anchor="w", pady=5, fill=tk.X)
            
            # 创建滑块容器
            ttk.Label(weight_frame, text="拖动滑块设置每个选项的权重比例：", 
                     foreground="gray").pack(anchor="w", pady=(10, 5), fill=tk.X)
            
            sliders_weight_frame = ttk.Frame(weight_frame)
            sliders_weight_frame.pack(fill=tk.BOTH, expand=True)
            
            slider_vars = []
            for i in range(q['options']):
                slider_frame = ttk.Frame(sliders_weight_frame)
                slider_frame.pack(fill=tk.X, pady=4, padx=(10, 20))
                slider_frame.columnconfigure(1, weight=1)

                # 显示选项文本（如果有的话）- 使用两行布局
                option_text = ""
                if i < len(q.get('option_texts', [])) and q['option_texts'][i]:
                    option_text = q['option_texts'][i]
                
                # 第一行：选项序号和完整文本
                text_label = ttk.Label(slider_frame, text=f"选项 {i+1}: {option_text}" if option_text else f"选项 {i+1}", 
                                       anchor="w", wraplength=500)
                text_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))

                # 第二行：滑块和权重值
                var = tk.DoubleVar(value=1.0)
                slider = ttk.Scale(slider_frame, from_=0, to=10, variable=var, orient=tk.HORIZONTAL)
                slider.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 5))

                value_label = ttk.Label(slider_frame, text="1.0", width=6, anchor="e")
                value_label.grid(row=1, column=2, sticky="e")

                def update_label(v=var, l=value_label):
                    l.config(text=f"{v.get():.1f}")

                var.trace_add("write", lambda *args, v=var, l=value_label: update_label(v, l))
                slider_vars.append(var)
            
            def save_and_next():
                mode = dist_var.get()
                q_type_map = {"3": "single", "5": "scale", "6": "matrix", "7": "dropdown"}
                q_type = q_type_map.get(type_code, "single")
                
                if mode == "random":
                    probs = -1
                    weights = None
                elif mode == "equal":
                    weights = [1.0] * q['options']
                    probs = normalize_probabilities(weights)
                else:
                    # 从滑块获取权重
                    weights = [var.get() for var in slider_vars]
                    if all(w == 0 for w in weights):
                        self._log_popup_error("错误", "至少要有一个选项的权重大于0")
                        return
                    probs = normalize_probabilities(weights)
                
                entry = QuestionEntry(
                    question_type=q_type,
                    probabilities=probs,
                    texts=None,
                    rows=q['rows'] if type_code == "6" else 1,
                    option_count=q['options'],
                    distribution_mode=mode,
                    custom_weights=weights
                )
                self.question_entries.append(entry)
                logging.info(
                    f"[Action Log] Wizard saved question #{current_index+1} type={q_type} mode={mode}"
                )
                wizard_win.destroy()
                self._show_wizard_for_question(questions_info, current_index + 1)
        
        # 按钮区域（固定在窗口底部）- 使用分隔线和更好的布局
        separator = ttk.Separator(wizard_win, orient='horizontal')
        separator.pack(side=tk.BOTTOM, fill=tk.X, before=canvas)
        
        btn_frame = ttk.Frame(wizard_win, padding=(15, 10, 15, 15))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, before=separator)
        
        # 左侧按钮组
        left_btn_frame = ttk.Frame(btn_frame)
        left_btn_frame.pack(side=tk.LEFT, fill=tk.X)
        
        if current_index > 0:
            prev_btn = ttk.Button(left_btn_frame, text="← 上一题", width=10,
                      command=lambda: self._go_back_in_wizard(wizard_win, questions_info, current_index))
            prev_btn.pack(side=tk.LEFT, padx=(0, 8), pady=2)
        
        skip_btn = ttk.Button(left_btn_frame, text="跳过", width=8, command=skip_question)
        skip_btn.pack(side=tk.LEFT, padx=8, pady=2)
        
        next_btn = ttk.Button(left_btn_frame, text="下一题 →", width=10, command=save_and_next)
        next_btn.pack(side=tk.LEFT, padx=8, pady=2)
        
        # 右侧取消按钮
        cancel_btn = ttk.Button(btn_frame, text="取消向导", width=10, command=_cleanup_mousewheel)
        cancel_btn.pack(side=tk.RIGHT, padx=(8, 0), pady=2)

    def _go_back_in_wizard(self, current_win, questions_info, current_index):
        if self._wizard_history and self._wizard_history[-1] == current_index:
            self._wizard_history.pop()
        prev_index = 0
        if self._wizard_history:
            prev_index = self._wizard_history.pop()
        if self.question_entries:
            self.question_entries.pop()
        current_win.destroy()
        self._show_wizard_for_question(questions_info, prev_index)

    def start_run(self):
        url_value = self.url_var.get().strip()
        if not url_value:
            self._log_popup_error("参数错误", "请填写问卷链接")
            return
        target_value = self.target_var.get().strip()
        if not target_value:
            self._log_popup_error("参数错误", "目标份数不能为空")
            return
        try:
            target = int(target_value)
            threads_count = int(self.thread_var.get().strip() or "0")
            if target <= 0 or threads_count <= 0:
                raise ValueError
        except ValueError:
            self._log_popup_error("参数错误", "目标份数和浏览器数量必须为正整数")
            return
        try:
            configure_probabilities(self.question_entries)
        except ValueError as exc:
            self._log_popup_error("配置错误", str(exc))
            return

        logging.info(
            f"[Action Log] Starting run url={url_value} target={target} threads={threads_count}"
        )

        global url, target_num, num_threads, fail_threshold, cur_num, cur_fail, stop_event
        url = url_value
        target_num = target
        num_threads = threads_count
        fail_threshold = max(1, math.ceil(target_num / 4) + 1)
        cur_num = 0
        cur_fail = 0
        stop_event = threading.Event()
        
        # 重置进度条
        self.progress_value = 0
        self.total_submissions = target
        self.current_submissions = 0
        self.progress_bar['value'] = 0
        self.progress_label.config(text="0%")

        self.running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("正在启动浏览器...")

        self.runner_thread = Thread(target=self._launch_threads, daemon=True)
        self.runner_thread.start()
        self._schedule_status_update()

    def _launch_threads(self):
        print(f"正在启动 {num_threads} 个浏览器窗口...")
        threads: List[Thread] = []
        for browser_index in range(num_threads):
            window_x = 50 + browser_index * 60
            window_y = 50
            thread = Thread(target=run, args=(window_x, window_y, stop_event, self), daemon=True)
            threads.append(thread)
        for thread in threads:
            thread.start()
            time.sleep(0.1)
        print("浏览器启动中，请稍候...")
        for thread in threads:
            thread.join()
        self.worker_threads = threads
        self.root.after(0, self._on_run_finished)

    def _schedule_status_update(self):
        status = f"已提交 {cur_num}/{target_num} 份 | 失败 {cur_fail} 次"
        self.status_var.set(status)
        
        # 更新进度条
        if target_num > 0:
            progress = int((cur_num / target_num) * 100)
            self.progress_bar['value'] = progress
            self.progress_label.config(text=f"{progress}%")
        
        if self.running:
            self.status_job = self.root.after(500, self._schedule_status_update)

    def _on_run_finished(self):
        self.running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED, text="停止")
        if self.status_job:
            self.root.after_cancel(self.status_job)
            self.status_job = None
        if cur_num >= target_num:
            msg = "任务完成"
        elif stop_event.is_set():
            msg = "已停止"
        else:
            msg = "已结束"
        self.status_var.set(f"{msg} | 已提交 {cur_num}/{target_num} 份 | 失败 {cur_fail} 次")
        
        # 最终更新进度条
        if cur_num >= target_num:
            self.progress_bar['value'] = 100
            self.progress_label.config(text="100%")
        else:
            if target_num > 0:
                progress = int((cur_num / target_num) * 100)
                self.progress_bar['value'] = progress
                self.progress_label.config(text=f"{progress}%")

    def stop_run(self):
        if not self.running:
            return
        stop_event.set()
        self.stop_button.config(state=tk.DISABLED, text="强制停止中...")
        self.status_var.set("正在强制停止所有浏览器...")
        
        for driver in self.active_drivers:
            try:
                driver.quit()
            except:
                pass
        self.active_drivers.clear()
        
        try:
            import subprocess
            if os.name == 'nt':
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"], 
                             capture_output=True, timeout=2)
                subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe", "/T"], 
                             capture_output=True, timeout=2)
            else:
                subprocess.run(["pkill", "-9", "chrome"], capture_output=True, timeout=2)
                subprocess.run(["pkill", "-9", "chromedriver"], capture_output=True, timeout=2)
        except:
            pass
        
        print("已强制停止所有浏览器")

    def on_close(self):
        # 停止日志刷新
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
        
        self.stop_run()
        
        # 只有在配置有实质性改动时才提示保存
        if not self._has_config_changed():
            # 配置未改动，直接关闭
            if self._log_refresh_job:
                try:
                    self.root.after_cancel(self._log_refresh_job)
                except Exception:
                    pass
            self.root.destroy()
            return
        
        # 检查是否有问卷链接或题目配置
        has_url = bool(self.url_var.get().strip())
        has_questions = bool(self.question_entries)
        
        if has_url or has_questions:
            # 生成保存提示信息
            if has_questions:
                msg = f"是否保存配置以便下次使用？\n\n已配置 {len(self.question_entries)} 道题目"
            else:
                msg = "是否保存问卷链接以便下次使用？"
            
            # 创建自定义对话框，包含保存、不保存、取消三个按钮
            dialog = tk.Toplevel(self.root)
            dialog.title("保存配置")
            dialog.geometry("300x150")
            dialog.resizable(False, False)
            dialog.transient(self.root)
            dialog.grab_set()
            
            # 居中显示对话框
            dialog.update_idletasks()
            dialog_width = dialog.winfo_width()
            dialog_height = dialog.winfo_height()
            screen_width = dialog.winfo_screenwidth()
            screen_height = dialog.winfo_screenheight()
            
            try:
                import ctypes
                from ctypes.wintypes import RECT
                work_area = RECT()
                ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
                work_width = work_area.right - work_area.left
                work_height = work_area.bottom - work_area.top
                work_x = work_area.left
                work_y = work_area.top
                x = work_x + (work_width - dialog_width) // 2
                y = work_y + (work_height - dialog_height) // 2
            except:
                x = (screen_width - dialog_width) // 2
                y = (screen_height - dialog_height) // 2
            
            x = max(0, x)
            y = max(0, y)
            dialog.geometry(f"+{x}+{y}")
            
            # 消息标签
            ttk.Label(dialog, text=msg, wraplength=280, justify=tk.CENTER).pack(pady=20)
            
            # 按钮容器
            button_frame = ttk.Frame(dialog)
            button_frame.pack(pady=(0, 10))
            
            # 结果变量
            result = tk.IntVar(value=None)
            
            def save_config():
                self._save_config()
                logging.info("[Action Log] Saved configuration before exit")
                result.set(1)
                dialog.destroy()
                if self._log_refresh_job:
                    try:
                        self.root.after_cancel(self._log_refresh_job)
                    except Exception:
                        pass
                self.root.destroy()
            
            def discard_config():
                # 不保存时，保持现有的config文件不删除，下次打开时会读取之前保存的config
                logging.info("[Action Log] Discarded new changes, keeping previous configuration")
                result.set(0)
                dialog.destroy()
                if self._log_refresh_job:
                    try:
                        self.root.after_cancel(self._log_refresh_job)
                    except Exception:
                        pass
                self.root.destroy()
            
            def cancel_close():
                logging.info("[Action Log] Cancelled exit")
                result.set(-1)
                dialog.destroy()
            
            ttk.Button(button_frame, text="保存", command=save_config, width=10).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="不保存", command=discard_config, width=10).pack(side=tk.LEFT, padx=5)
            ttk.Button(button_frame, text="取消", command=cancel_close, width=10).pack(side=tk.LEFT, padx=5)
            
            # 焦点设置到取消按钮作为默认
            dialog.focus_set()
            
            return
        
        if self._log_refresh_job:
            try:
                self.root.after_cancel(self._log_refresh_job)
            except Exception:
                pass
        self.root.destroy()

    def _center_window(self):
        """将窗口放在屏幕上方中央"""
        self.root.update_idletasks()
        
        # 获取窗口大小
        window_width = self.root.winfo_width()
        window_height = self.root.winfo_height()
        
        # 获取屏幕大小（包括任务栏）
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # 在 Windows 上获取工作区（不包括任务栏）
        try:
            import ctypes
            from ctypes.wintypes import RECT
            
            # 获取工作区坐标
            work_area = RECT()
            ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
            
            work_width = work_area.right - work_area.left
            work_height = work_area.bottom - work_area.top
            work_x = work_area.left
            work_y = work_area.top
            
            # 使用工作区计算位置 - 水平居中，垂直放在上方
            x = work_x + (work_width - window_width) // 2
            y = max(work_y + 20, work_y + (work_height - window_height) // 5)
        except:
            # 如果获取工作区失败，回退到简单计算
            x = (screen_width - window_width) // 2
            y = max(20, (screen_height - window_height) // 5)
        
        # 确保坐标不为负数
        x = max(0, x)
        y = max(0, y)
        
        # 设置窗口位置
        self.root.geometry(f"+{x}+{y}")

    def _get_config_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

    def _save_config(self):
        try:
            # 获取 PanedWindow 分隔条位置
            paned_sash_pos = None
            try:
                paned_sash_pos = self.main_paned.sashpos(0)
            except Exception:
                pass
            
            config = {
                "url": self.url_var.get(),
                "target_num": self.target_var.get(),
                "num_threads": self.thread_var.get(),
                "paned_position": paned_sash_pos,
                "questions": [
                    {
                        "question_type": entry.question_type,
                        "probabilities": entry.probabilities if not isinstance(entry.probabilities, int) else entry.probabilities,
                        "texts": entry.texts,
                        "rows": entry.rows,
                        "option_count": entry.option_count,
                        "distribution_mode": entry.distribution_mode,
                        "custom_weights": entry.custom_weights,
                    }
                    for entry in self.question_entries
                ],
            }
            with open(self._get_config_path(), "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")

    def _load_config(self):
        config_path = self._get_config_path()
        if not os.path.exists(config_path):
            return
        
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            if "url" in config:
                self.url_var.set(config["url"])
            if "target_num" in config:
                self.target_var.set(config["target_num"])
            if "num_threads" in config:
                self.thread_var.set(config["num_threads"])
            
            # 恢复 PanedWindow 分隔条位置
            if "paned_position" in config and config["paned_position"] is not None:
                def restore_paned_pos():
                    try:
                        self.main_paned.sashpos(0, config["paned_position"])
                        self._paned_position_restored = True
                    except Exception:
                        pass
                self.root.after(100, restore_paned_pos)
            
            if "questions" in config and config["questions"]:
                self.question_entries.clear()
                for q_data in config["questions"]:
                    entry = QuestionEntry(
                        question_type=q_data.get("question_type", "single"),
                        probabilities=q_data.get("probabilities", -1),
                        texts=q_data.get("texts"),
                        rows=q_data.get("rows", 1),
                        option_count=q_data.get("option_count", 0),
                        distribution_mode=q_data.get("distribution_mode", "random"),
                        custom_weights=q_data.get("custom_weights"),
                    )
                    self.question_entries.append(entry)
                self._refresh_tree()
                print(f"已加载上次配置：{len(self.question_entries)} 道题目")
            
            # 加载完成后保存初始配置以用于变化检测
            self._save_initial_config()
            self._config_changed = False
        except Exception as e:
            print(f"加载配置失败: {e}")

    def _save_initial_config(self):
        """保存初始配置状态以便检测后续变化"""
        self._initial_config = {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities if not isinstance(entry.probabilities, int) else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                }
                for entry in self.question_entries
            ],
        }

    def _mark_config_changed(self):
        """标记配置已改动"""
        self._config_changed = True

    def _has_config_changed(self) -> bool:
        """检查配置是否有实质性改动"""
        current_config = {
            "url": self.url_var.get(),
            "target_num": self.target_var.get(),
            "num_threads": self.thread_var.get(),
            "questions": [
                {
                    "question_type": entry.question_type,
                    "probabilities": entry.probabilities if not isinstance(entry.probabilities, int) else entry.probabilities,
                    "texts": entry.texts,
                    "rows": entry.rows,
                    "option_count": entry.option_count,
                    "distribution_mode": entry.distribution_mode,
                    "custom_weights": entry.custom_weights,
                }
                for entry in self.question_entries
            ],
        }
        return current_config != self._initial_config

    def _check_updates_on_startup(self):
        """在启动时后台检查更新"""
        def check():
            try:
                update_info = UpdateManager.check_updates()
                if update_info:
                    self.update_info = update_info
                    self.root.after(0, self._show_update_notification)
            except Exception as e:
                logging.debug(f"启动时检查更新失败: {e}")
        
        thread = Thread(target=check, daemon=True)
        thread.start()

    def _show_update_notification(self):
        """显示更新通知"""
        if not self.update_info:
            return
        
        info = self.update_info
        release_notes = info.get('release_notes', '')
        # 限制发布说明长度，避免弹窗过大
        release_notes_preview = release_notes[:300] if release_notes else "暂无更新说明"
        if len(release_notes) > 300:
            release_notes_preview += "\n..."
        
        msg = (
            f"检测到新版本 v{info['version']}\n"
            f"当前版本 v{info['current_version']}\n\n"
            f"发布说明:\n{release_notes_preview}\n\n"
            f"是否要立即下载更新？"
        )
        
        if self._log_popup_confirm("检查到更新", msg):
            logging.info("[Action Log] User accepted update notification")
            self._perform_update()
        else:
            logging.info("[Action Log] User declined update notification")

    def check_for_updates(self):
        """手动检查更新"""
        self.root.config(cursor="wait")
        self.root.update()
        
        try:
            update_info = UpdateManager.check_updates()
            if update_info:
                self.update_info = update_info
                msg = (
                    f"检测到新版本！\n\n"
                    f"当前版本: v{update_info['current_version']}\n"
                    f"新版本: v{update_info['version']}\n\n"
                    f"发布说明:\n{update_info['release_notes'][:200]}\n\n"
                    f"立即更新？"
                )
                if self._log_popup_confirm("检查到更新", msg):
                    logging.info("[Action Log] User triggered manual update")
                    self._perform_update()
                else:
                    logging.info("[Action Log] User postponed manual update")
            else:
                self._log_popup_info("检查更新", f"当前已是最新版本 v{__VERSION__}")
        except Exception as e:
            self._log_popup_error("检查更新失败", f"错误: {str(e)}")
        finally:
            self.root.config(cursor="")

    def _perform_update(self):
        """执行更新"""
        if not self.update_info:
            return
        
        update_info = self.update_info
        
        # 显示更新进度窗口
        progress_win = tk.Toplevel(self.root)
        progress_win.title("正在更新")
        progress_win.geometry("500x200")
        progress_win.resizable(False, False)
        progress_win.transient(self.root)
        progress_win.grab_set()
        
        # 居中显示进度窗口
        progress_win.update_idletasks()
        win_width = progress_win.winfo_width()
        win_height = progress_win.winfo_height()
        screen_width = progress_win.winfo_screenwidth()
        screen_height = progress_win.winfo_screenheight()
        
        try:
            import ctypes
            from ctypes.wintypes import RECT
            work_area = RECT()
            ctypes.windll.user32.SystemParametersInfoA(48, 0, ctypes.byref(work_area), 0)
            work_width = work_area.right - work_area.left
            work_height = work_area.bottom - work_area.top
            work_x = work_area.left
            work_y = work_area.top
            x = work_x + (work_width - win_width) // 2
            y = work_y + (work_height - win_height) // 2
        except:
            x = (screen_width - win_width) // 2
            y = (screen_height - win_height) // 2
        
        x = max(0, x)
        y = max(0, y)
        progress_win.geometry(f"+{x}+{y}")
        
        frame = ttk.Frame(progress_win, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        
        title_label = ttk.Label(frame, text="正在下载新版本...", font=('', 10, 'bold'))
        title_label.pack(pady=(0, 10))
        
        # 文件名标签
        file_label = ttk.Label(frame, text=f"文件: {update_info['file_name']}", foreground="gray")
        file_label.pack(pady=(0, 5))
        
        # 进度条（确定模式）
        progress = ttk.Progressbar(frame, mode='determinate', maximum=100)
        progress.pack(fill=tk.X, pady=10)
        
        # 进度文字
        progress_label = ttk.Label(frame, text="0%", foreground="gray")
        progress_label.pack(pady=(0, 5))
        
        # 状态标签
        status_label = ttk.Label(frame, text="准备下载...", foreground="gray", wraplength=450)
        status_label.pack(pady=10)
        
        progress_win.update()
        
        def update_progress(downloaded, total):
            """更新进度条"""
            if total > 0:
                percent = (downloaded / total) * 100
                progress['value'] = percent
                # 格式化文件大小
                downloaded_mb = downloaded / (1024 * 1024)
                total_mb = total / (1024 * 1024)
                progress_label.config(text=f"{percent:.1f}% ({downloaded_mb:.1f}MB / {total_mb:.1f}MB)")
                progress_win.update()
        
        def do_update():
            try:
                status_label.config(text="正在更新...")
                progress_win.update()
                
                downloaded_file = UpdateManager.download_update(
                    update_info['download_url'],
                    update_info['file_name'],
                    progress_callback=update_progress
                )
                
                if downloaded_file:
                    status_label.config(text=f"新版本下载成功！合并文件中...")
                    progress_label.config(text="100%")
                    progress['value'] = 100
                    progress_win.update()
                    time.sleep(2)
                    progress_win.destroy()
                    
                    # 询问是否立即运行新版本
                    should_launch = self._log_popup_confirm("更新完成", 
                        f"新版本已下载到:\n{downloaded_file}\n\n是否立即运行新版本？")
                    UpdateManager.schedule_running_executable_deletion(downloaded_file)
                    if should_launch:
                        try:
                            subprocess.Popen([downloaded_file])
                            self.on_close()
                        except Exception as e:
                            logging.error("[Action Log] Failed to launch downloaded update")
                            self._log_popup_error("启动失败", f"无法启动新版本: {e}")
                    else:
                        logging.info("[Action Log] Deferred launching downloaded update")
                else:
                    status_label.config(text="下载失败", foreground="red")
                    progress_win.update()
                    time.sleep(2)
                    progress_win.destroy()
                    self._log_popup_error("更新失败", "下载文件失败，请稍后重试")
            except Exception as e:
                logging.error(f"更新过程中出错: {e}")
                status_label.config(text=f"错误: {str(e)}", foreground="red")
                progress_win.update()
                time.sleep(2)
                progress_win.destroy()
                self._log_popup_error("更新失败", f"更新过程出错: {str(e)}")
        
        thread = Thread(target=do_update, daemon=True)
        thread.start()

    def show_about(self):
        """显示关于对话框"""
        about_text = (
            f"fuck-wjx（问卷星速写）\n\n"
            f"当前版本 v{__VERSION__}\n\n"
            f"GitHub项目地址: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}\n"
            f"有问题可在 GitHub 提交 issue 或发送电子邮件至 help@hungrym0.top\n\n"
            f"官方网站: https://www.hungrym0.top/fuck-wjx\n"
            f"©2025 HUNGRY_M0 版权所有"
        )
        logging.info("[Action Log] Displaying About dialog")
        self._log_popup_info("关于", about_text)

    def run(self):
        self.root.mainloop()


def main():
    setup_logging()
    gui = SurveyGUI()
    gui.run()


if __name__ == "__main__":
    main()
