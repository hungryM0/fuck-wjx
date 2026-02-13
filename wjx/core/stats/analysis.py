"""统计分析引擎

基于原始答卷数据（JSONL）进行真实的信效度分析。

提供的统计指标：
- Cronbach's Alpha（信度）：评估问卷内部一致性
  - 全量 Alpha：所有题目的整体一致性
  - 分维度 Alpha：各因子的内部一致性（EFA 成功时）
- KMO 检验（效度）：评估数据是否适合因子分析
- Bartlett 球形检验（效度）：检验变量间是否存在相关性
- 探索性因子分析（EFA）：
  - 自动判定问卷维度数量（特征值 > 1 的 Kaiser 准则）
  - Varimax 旋转生成因子载荷矩阵
  - 题目自动归属到载荷最高的因子
  - 分维度计算 Cronbach's Alpha

所有函数都设计为纯函数，不依赖全局状态，方便在后台线程调用。
"""

import json
import os
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import logging
from wjx.utils.logging.log_utils import log_suppressed_exception




import numpy as np
import pandas as pd

# 适合进行信效度分析的题型（有序数值型选项）
_SCALE_TYPES = {"single", "scale", "score", "dropdown", "slider", "matrix"}

# 分析所需的最少样本数
_MIN_SAMPLES = 3
# 分析所需的最少题目数
_MIN_ITEMS = 2


@dataclass
class FactorInfo:
    """单个因子的详细信息

    Attributes:
        factor_id: 因子编号（从 1 开始）
        factor_name: 因子名称（如 "Q1-Q3 维度"）
        question_nums: 归属该因子的题号列表
        cronbach_alpha: 该因子的 Cronbach's Alpha 系数
        eigenvalue: 该因子的特征值
        variance_explained: 该因子解释的方差百分比
    """
    factor_id: int
    factor_name: str
    question_nums: List[int]
    cronbach_alpha: Optional[float] = None
    eigenvalue: Optional[float] = None
    variance_explained: Optional[float] = None


@dataclass
class AnalysisResult:
    """统计分析结果

    Attributes:
        cronbach_alpha: 全量 Cronbach's Alpha 系数，None 表示无法计算
        kmo_value: KMO 检验值，None 表示无法计算
        bartlett_chi2: Bartlett 球形检验卡方值
        bartlett_p: Bartlett 球形检验 p 值
        sample_count: 用于分析的样本数
        item_count: 用于分析的题目数（变量数）
        item_columns: 参与分析的题号列表
        error: 错误信息，None 表示成功

        # EFA 相关字段
        efa_performed: 是否成功执行了探索性因子分析
        n_factors: 提取的因子数量
        factors: 各因子的详细信息列表
        eigenvalues: 所有特征值列表（用于碎石图）
        loadings_matrix: 旋转后的因子载荷矩阵（DataFrame，行=题目，列=因子）
        total_variance_explained: 所有因子累计解释的方差百分比
    """
    cronbach_alpha: Optional[float] = None
    kmo_value: Optional[float] = None
    bartlett_chi2: Optional[float] = None
    bartlett_p: Optional[float] = None
    sample_count: int = 0
    item_count: int = 0
    item_columns: List[int] = field(default_factory=list)
    error: Optional[str] = None

    # EFA 相关字段
    efa_performed: bool = False
    n_factors: int = 0
    factors: List[FactorInfo] = field(default_factory=list)
    eigenvalues: List[float] = field(default_factory=list)
    loadings_matrix: Optional[pd.DataFrame] = None
    total_variance_explained: Optional[float] = None


def load_raw_data(jsonl_path: str) -> List[Dict]:
    """从 JSONL 文件加载原始答卷数据

    Args:
        jsonl_path: JSONL 文件路径

    Returns:
        答卷记录列表，每个元素是一行 JSON 解析后的 dict
    """
    records = []
    if not os.path.exists(jsonl_path):
        return records

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return records


def build_score_matrix(records: List[Dict]) -> Tuple[pd.DataFrame, List[int]]:
    """从原始答卷数据构建得分矩阵

    只提取适合信效度分析的题型（量表题、评分题、单选题、下拉题、滑块题、矩阵题），
    将它们的选项索引作为数值得分，构建 样本×题目 的 DataFrame。

    对于矩阵题，每一行会被展开为独立的变量（如 q6_0, q6_1）。

    Args:
        records: load_raw_data() 返回的原始数据

    Returns:
        (df, question_nums) 元组：
        - df: pandas DataFrame，行=样本，列=题号（如 "q1", "q3", "q6_0", "q6_1"）
        - question_nums: 参与分析的题号列表（int，矩阵题的子行不单独列出）
    """
    if not records:
        return pd.DataFrame(), []

    # 第一遍扫描：找出所有适合分析的题号和矩阵题的行数
    scale_questions: Dict[str, str] = {}  # q_num_str → question_type
    matrix_rows: Dict[str, set] = {}  # q_num_str → set of row_keys (for matrix questions)

    for record in records:
        answers = record.get("answers", {})
        for q_num_str, answer_data in answers.items():
            q_type = answer_data.get("type", "")
            if q_type in _SCALE_TYPES:
                if q_num_str not in scale_questions:
                    scale_questions[q_num_str] = q_type

                # 如果是矩阵题，收集所有行的键
                if q_type == "matrix":
                    value = answer_data.get("value")
                    if isinstance(value, dict):
                        if q_num_str not in matrix_rows:
                            matrix_rows[q_num_str] = set()
                        matrix_rows[q_num_str].update(value.keys())

    if not scale_questions:
        return pd.DataFrame(), []

    # 按题号排序
    sorted_q_nums = sorted(scale_questions.keys(), key=lambda x: int(x))
    question_nums = [int(q) for q in sorted_q_nums]

    # 第二遍扫描：构建得分矩阵
    rows = []
    for record in records:
        answers = record.get("answers", {})
        row = {}

        for q_num_str in sorted_q_nums:
            answer_data = answers.get(q_num_str)
            q_type = scale_questions[q_num_str]

            if answer_data is not None:
                value = answer_data.get("value")

                # 处理矩阵题：展开每一行
                if q_type == "matrix" and isinstance(value, dict):
                    # 对矩阵题的每一行，创建独立的列（如 q6_0, q6_1）
                    for row_key in sorted(matrix_rows.get(q_num_str, set()), key=lambda x: int(x) if x.isdigit() else x):
                        col_name = f"q{q_num_str}_{row_key}"
                        row_value = value.get(row_key)
                        if row_value is not None and isinstance(row_value, (int, float)):
                            row[col_name] = row_value
                        else:
                            row[col_name] = np.nan

                # 处理其他题型
                elif value is not None and isinstance(value, (int, float)):
                    row[f"q{q_num_str}"] = value
                else:
                    row[f"q{q_num_str}"] = np.nan
            else:
                # 如果是矩阵题，需要为每一行都填充 NaN
                if q_type == "matrix":
                    for row_key in sorted(matrix_rows.get(q_num_str, set()), key=lambda x: int(x) if x.isdigit() else x):
                        row[f"q{q_num_str}_{row_key}"] = np.nan
                else:
                    row[f"q{q_num_str}"] = np.nan

        rows.append(row)

    df = pd.DataFrame(rows)

    # 删除全为 NaN 的列（某些题可能没有任何有效数据）
    df = df.dropna(axis=1, how="all")

    # 更新 question_nums 以匹配实际保留的列
    # 注意：矩阵题的子行（如 q6_0）会被提取为题号 6
    question_nums = []
    for col in df.columns:
        if '_' in col:
            # 矩阵题的子行，提取主题号
            q_num = int(col.split('_')[0][1:])
        else:
            # 普通题
            q_num = int(col[1:])
        if q_num not in question_nums:
            question_nums.append(q_num)
    question_nums.sort()

    return df, question_nums


def calculate_cronbach_alpha(df: pd.DataFrame) -> Optional[float]:
    """计算 Cronbach's Alpha 系数

    公式：α = (k / (k-1)) * (1 - Σσ²ᵢ / σ²ₜ)

    Args:
        df: 得分矩阵（行=样本，列=题目），必须至少 2 列、3 行

    Returns:
        Alpha 系数值（0~1 之间），无法计算返回 None
    """
    # 删除含缺失值的行
    df_clean = df.dropna()

    n_samples, n_items = df_clean.shape
    if n_items < _MIN_ITEMS or n_samples < _MIN_SAMPLES:
        return None

    # 每道题的方差
    item_variances = df_clean.var(axis=0, ddof=1)

    # 如果有任何题方差为 0（所有人选了同一个答案），无法计算
    if (item_variances == 0).any():
        return None

    sum_item_var = item_variances.sum()

    # 总分的方差
    total_scores = df_clean.sum(axis=1)
    total_var = total_scores.var(ddof=1)

    if total_var == 0:
        return None

    k = n_items
    alpha = (k / (k - 1)) * (1 - sum_item_var / total_var)

    # Alpha 理论上可以为负值（题目间负相关），但通常限制在合理范围
    return float(alpha)


def calculate_validity(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """计算效度指标（KMO 和 Bartlett 球形检验）

    Args:
        df: 得分矩阵（行=样本，列=题目）

    Returns:
        (kmo_value, bartlett_chi2, bartlett_p) 元组，
        任一项无法计算时为 None
    """
    # 删除含缺失值的行
    df_clean = df.dropna()

    n_samples, n_items = df_clean.shape
    if n_items < _MIN_ITEMS or n_samples < _MIN_SAMPLES:
        return None, None, None

    # 方差为 0 的列无法参与计算（会导致相关矩阵奇异）
    zero_var_cols = df_clean.columns[df_clean.var(axis=0) == 0]
    if len(zero_var_cols) > 0:
        df_clean = df_clean.drop(columns=zero_var_cols)
        if df_clean.shape[1] < _MIN_ITEMS:
            return None, None, None

    try:
        from factor_analyzer.factor_analyzer import (
            calculate_bartlett_sphericity,
            calculate_kmo,
        )
    except ImportError:
        return None, None, None

    kmo_value = None
    bartlett_chi2 = None
    bartlett_p = None

    # 捕获并以WARNING级别记录计算过程中的数学警告（矩阵奇异、除以零等）
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        try:
            kmo_per_item, kmo_overall = calculate_kmo(df_clean)
            kmo_value = float(kmo_overall)
        except Exception as exc:
            log_suppressed_exception("calculate_validity: kmo_per_item, kmo_overall = calculate_kmo(df_clean)", exc, level=logging.WARNING)

        try:
            chi2, p_value = calculate_bartlett_sphericity(df_clean)
            bartlett_chi2 = float(chi2)
            bartlett_p = float(p_value)
        except Exception as exc:
            log_suppressed_exception("calculate_validity: chi2, p_value = calculate_bartlett_sphericity(df_clean)", exc, level=logging.WARNING)
        
        # 将捕获的警告以WARNING级别记录到日志
        for warning in w:
            logging.warning(
                "统计分析数学警告: %s (来自 %s:%d)",
                str(warning.message),
                warning.filename,
                warning.lineno
            )

    return kmo_value, bartlett_chi2, bartlett_p


def perform_efa(df: pd.DataFrame) -> Tuple[Optional[int], Optional[List[float]], Optional[pd.DataFrame]]:
    """执行探索性因子分析（EFA）

    使用主成分分析（PCA）+ Varimax 旋转，模拟 SPSS 的因子分析流程。
    根据特征值 > 1 的 Kaiser 准则自动判定因子数量。

    Args:
        df: 得分矩阵（行=样本，列=题目）

    Returns:
        (n_factors, eigenvalues, loadings_df) 元组：
        - n_factors: 提取的因子数量（特征值 > 1 的数量）
        - eigenvalues: 所有特征值列表（降序排列）
        - loadings_df: 旋转后的因子载荷矩阵（DataFrame，行=题目列名，列=因子编号）
        任一项失败返回 None
    """
    # 删除含缺失值的行
    df_clean = df.dropna()

    n_samples, n_items = df_clean.shape
    if n_items < _MIN_ITEMS or n_samples < _MIN_SAMPLES:
        return None, None, None

    # 方差为 0 的列无法参与计算
    zero_var_cols = df_clean.columns[df_clean.var(axis=0) == 0]
    if len(zero_var_cols) > 0:
        df_clean = df_clean.drop(columns=zero_var_cols)
        if df_clean.shape[1] < _MIN_ITEMS:
            return None, None, None

    try:
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        logging.warning("scikit-learn 库未安装，无法执行 EFA")
        return None, None, None

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        try:
            # 标准化数据（PCA 要求）
            scaler = StandardScaler()
            data_scaled = scaler.fit_transform(df_clean)

            # 第一步：用 PCA 获取所有特征值
            # n_components 不能超过 min(样本数, 题目数)
            max_components = min(n_samples, n_items)
            pca_full = PCA(n_components=max_components)
            pca_full.fit(data_scaled)

            # 获取特征值（方差解释量）
            eigenvalues = pca_full.explained_variance_.tolist()

            # 根据 Kaiser 准则（特征值 > 1）判定因子数
            n_factors = sum(1 for ev in eigenvalues if ev > 1.0)

            # 如果只有 1 个因子或没有因子，返回 None（降级到全量 Alpha）
            if n_factors <= 1:
                logging.info(f"EFA 只提取到 {n_factors} 个因子，降级到全量分析")
                return None, eigenvalues, None

            # 第二步：提取指定数量的因子
            pca = PCA(n_components=n_factors)
            pca.fit(data_scaled)

            # 获取因子载荷矩阵（成分矩阵）
            # 载荷 = 特征向量 * sqrt(特征值)
            components = pca.components_.T  # 转置，使得行=变量，列=因子
            loadings = components * np.sqrt(pca.explained_variance_)

            # Varimax 旋转
            loadings_rotated = _varimax_rotation(loadings)

            # 构建 DataFrame
            loadings_df = pd.DataFrame(
                loadings_rotated,
                index=df_clean.columns,
                columns=[f"Factor{i+1}" for i in range(n_factors)]
            )

            logging.info(f"EFA 成功：提取 {n_factors} 个因子")
            return n_factors, eigenvalues, loadings_df

        except Exception as e:
            logging.warning(f"EFA 执行失败: {e}")
            return None, None, None

        finally:
            # 记录警告
            for warning in w:
                logging.warning(
                    "EFA 数学警告: %s (来自 %s:%d)",
                    str(warning.message),
                    warning.filename,
                    warning.lineno
                )


def _varimax_rotation(loadings: np.ndarray, max_iter: int = 100, tol: float = 1e-6) -> np.ndarray:
    """Varimax 旋转算法

    最大化因子载荷的方差，使得每个变量在某个因子上有高载荷，在其他因子上有低载荷。

    Args:
        loadings: 未旋转的因子载荷矩阵（行=变量，列=因子）
        max_iter: 最大迭代次数
        tol: 收敛阈值

    Returns:
        旋转后的因子载荷矩阵
    """
    n_vars, n_factors = loadings.shape

    # 如果只有 1 个因子，无需旋转
    if n_factors == 1:
        return loadings

    # 初始化旋转矩阵为单位矩阵
    rotation_matrix = np.eye(n_factors)

    for _ in range(max_iter):
        # 计算旋转后的载荷
        rotated = loadings @ rotation_matrix

        # 计算梯度（简化的 Varimax 准则）
        # 目标：最大化 sum((载荷^2)^2) - sum(载荷^2)^2 / n_vars
        normalized = rotated / np.sqrt(np.sum(rotated ** 2, axis=0, keepdims=True))
        u, s, vt = np.linalg.svd(loadings.T @ (normalized ** 3 - normalized @ np.diag(np.sum(normalized ** 2, axis=0)) / n_vars))

        # 更新旋转矩阵
        new_rotation = u @ vt

        # 检查收敛
        if np.allclose(rotation_matrix, new_rotation, atol=tol):
            break

        rotation_matrix = new_rotation

    return loadings @ rotation_matrix


def assign_questions_to_factors(loadings_df: pd.DataFrame, question_nums: List[int]) -> Dict[int, List[int]]:
    """根据因子载荷矩阵，将题目分配到各因子

    策略：每道题归属到载荷绝对值最高的因子。

    Args:
        loadings_df: 因子载荷矩阵（行=题目列名如 "q1", "q6_0"，列=因子如 "Factor1"）
        question_nums: 原始题号列表（用于验证）

    Returns:
        字典 {factor_id: [question_nums]}，factor_id 从 1 开始
    """
    factor_assignment: Dict[int, List[int]] = {}

    for col_name in loadings_df.index:
        # 提取题号（col_name 格式为 "q1", "q2", "q6_0", "q6_1" 等）
        # 对于矩阵题的子行（如 q6_0），提取主题号 6
        if '_' in col_name:
            q_num = int(col_name.split('_')[0][1:])
        else:
            q_num = int(col_name[1:])

        # 找到该题在所有因子上的载荷绝对值最大的因子
        loadings_row = loadings_df.loc[col_name]
        max_factor_col = loadings_row.abs().idxmax()  # 返回列名如 "Factor1"
        factor_id = int(max_factor_col.replace("Factor", ""))

        if factor_id not in factor_assignment:
            factor_assignment[factor_id] = []
        # 避免重复添加同一题号（矩阵题的多行会映射到同一题号）
        if q_num not in factor_assignment[factor_id]:
            factor_assignment[factor_id].append(q_num)

    # 对每个因子的题号列表排序
    for factor_id in factor_assignment:
        factor_assignment[factor_id].sort()

    return factor_assignment


def calculate_factor_alphas(df: pd.DataFrame, factor_assignment: Dict[int, List[int]]) -> Dict[int, Optional[float]]:
    """分因子计算 Cronbach's Alpha

    Args:
        df: 得分矩阵（行=样本，列=题目，列名如 "q1", "q2", "q6_0", "q6_1"）
        factor_assignment: 因子分配字典 {factor_id: [question_nums]}

    Returns:
        字典 {factor_id: alpha_value}，无法计算的因子返回 None
    """
    factor_alphas: Dict[int, Optional[float]] = {}

    for factor_id, q_nums in factor_assignment.items():
        # 构建该因子的子矩阵
        # 需要找到所有匹配的列，包括矩阵题的子行（如 q6_0, q6_1）
        col_names = []
        for q in q_nums:
            # 查找所有以 "q{q}" 开头的列（包括 q6, q6_0, q6_1 等）
            matching_cols = [c for c in df.columns if c == f"q{q}" or c.startswith(f"q{q}_")]
            col_names.extend(matching_cols)

        if len(col_names) < _MIN_ITEMS:
            factor_alphas[factor_id] = None
            continue

        df_factor = df[col_names]
        alpha = calculate_cronbach_alpha(df_factor)
        factor_alphas[factor_id] = alpha

    return factor_alphas


def run_analysis(jsonl_path: str) -> AnalysisResult:
    """执行完整的统计分析（入口函数）

    从 JSONL 文件读取数据，构建得分矩阵，计算信度和效度。
    这个函数设计为在后台线程中调用，不会阻塞 GUI。

    Args:
        jsonl_path: 原始答卷 JSONL 文件路径

    Returns:
        AnalysisResult 包含所有分析结果
    """
    result = AnalysisResult()

    # 1. 加载数据
    if not jsonl_path or not os.path.exists(jsonl_path):
        result.error = "未找到原始数据文件"
        return result

    records = load_raw_data(jsonl_path)
    if not records:
        result.error = "原始数据文件为空"
        return result

    # 2. 构建得分矩阵
    df, question_nums = build_score_matrix(records)
    result.item_columns = question_nums

    if df.empty:
        result.error = "没有找到适合分析的题型（需要量表题、评分题、单选题等）"
        return result

    # 删除含缺失值的行，计算可用样本数
    df_clean = df.dropna()
    result.sample_count = len(df_clean)
    result.item_count = df_clean.shape[1] if not df_clean.empty else 0

    if result.sample_count < _MIN_SAMPLES:
        result.error = f"样本数不足（当前 {result.sample_count} 份，至少需要 {_MIN_SAMPLES} 份）"
        return result

    if result.item_count < _MIN_ITEMS:
        result.error = f"适合分析的题目不足（当前 {result.item_count} 道，至少需要 {_MIN_ITEMS} 道）"
        return result

    # 3. 计算信度（Cronbach's Alpha - 全量）
    try:
        result.cronbach_alpha = calculate_cronbach_alpha(df)
    except Exception as exc:
        log_suppressed_exception("run_analysis: result.cronbach_alpha = calculate_cronbach_alpha(df)", exc, level=logging.WARNING)

    # 4. 计算效度（KMO + Bartlett）
    try:
        kmo, chi2, p = calculate_validity(df)
        result.kmo_value = kmo
        result.bartlett_chi2 = chi2
        result.bartlett_p = p
    except Exception as exc:
        log_suppressed_exception("run_analysis: kmo, chi2, p = calculate_validity(df)", exc, level=logging.WARNING)

    # 5. 执行探索性因子分析（EFA）
    try:
        n_factors, eigenvalues, loadings_df = perform_efa(df)

        # 保存特征值（即使 EFA 失败也可能有特征值）
        if eigenvalues is not None:
            result.eigenvalues = eigenvalues

        # 如果成功提取多个因子，进行分维度分析
        if n_factors is not None and n_factors > 1 and loadings_df is not None:
            result.efa_performed = True
            result.n_factors = n_factors
            result.loadings_matrix = loadings_df

            # 计算总方差解释率
            if eigenvalues:
                total_variance = sum(eigenvalues)
                explained_variance = sum(eigenvalues[:n_factors])
                result.total_variance_explained = (explained_variance / total_variance) * 100

            # 分配题目到各因子
            factor_assignment = assign_questions_to_factors(loadings_df, question_nums)

            # 计算各因子的 Alpha
            factor_alphas = calculate_factor_alphas(df, factor_assignment)

            # 构建 FactorInfo 列表
            for factor_id in sorted(factor_assignment.keys()):
                q_nums = factor_assignment[factor_id]

                # 生成因子名称（如 "Q1-Q3 维度"）
                if len(q_nums) == 1:
                    factor_name = f"Q{q_nums[0]} 维度"
                else:
                    factor_name = f"Q{q_nums[0]}-Q{q_nums[-1]} 维度"

                # 获取该因子的特征值和方差解释率
                eigenvalue = None
                variance_explained = None
                if eigenvalues and factor_id <= len(eigenvalues):
                    eigenvalue = eigenvalues[factor_id - 1]
                    total_variance = sum(eigenvalues)
                    variance_explained = (eigenvalue / total_variance) * 100

                factor_info = FactorInfo(
                    factor_id=factor_id,
                    factor_name=factor_name,
                    question_nums=q_nums,
                    cronbach_alpha=factor_alphas.get(factor_id),
                    eigenvalue=eigenvalue,
                    variance_explained=variance_explained
                )
                result.factors.append(factor_info)

            logging.info(f"EFA 分析完成：{n_factors} 个因子，总方差解释率 {result.total_variance_explained:.2f}%")
        else:
            # EFA 失败或只有 1 个因子，降级到全量分析
            logging.info("EFA 未执行或只有单因子，使用全量 Alpha")
            result.efa_performed = False

    except Exception as e:
        logging.warning(f"EFA 流程异常: {e}")
        result.efa_performed = False

    return result
