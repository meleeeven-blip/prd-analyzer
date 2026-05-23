#!/usr/bin/env python3
"""
evaluate.py — 对比 AI 分析结果与人工标注 ground truth，量化评测效果。

用法：
    python evaluate.py                      # token-F1 匹配，打印报告
    python evaluate.py --verbose            # 显示每条匹配/未匹配详情
    python evaluate.py --threshold 0.4      # 调高匹配阈值（默认 0.35）
    python evaluate.py --save report.json   # 保存完整 JSON 报告
    python evaluate.py --llm-judge          # 用 Bailian LLM 做语义裁判（更准确）
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from openai import OpenAI
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.panel import Panel

from src.analyzer import PRDAnalyzer
from src.models import PRDAnalysisResult

app = typer.Typer(add_completion=False)
console = Console(force_terminal=True, highlight=False)

DEFAULT_PRD_PATH = Path("tests/fixtures/complex_prd.md")
DEFAULT_GT_PATH = Path("tests/fixtures/complex_prd_ground_truth.json")
BAILIAN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# ---------------------------------------------------------------------------
# Token-F1 匹配
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """CJK-aware: 中文段使用字符 bigram，英文/数字保留整词（无需 jieba）。"""
    text = text.lower()
    tokens: set[str] = set()
    for part in re.split(r'[\s，。、；：？！「」【】（）\(\)\.\,\;\:\?\!\-——/]+', text):
        if not part:
            continue
        if any('一' <= c <= '鿿' for c in part):
            # 中文段：滑动 bigram，每两个相邻汉字构成一个 token
            for i in range(len(part) - 1):
                tokens.add(part[i:i+2])
        elif len(part) > 1:
            # 英文词、数字、ID（如 F-07、200ms）整体保留
            tokens.add(part)
    return tokens


def _token_f1(pred: str, ref: str) -> float:
    """计算两段文本的 token 级 F1 分数。"""
    p_tok = _tokenize(pred)
    r_tok = _tokenize(ref)
    if not p_tok or not r_tok:
        return 0.0
    common = p_tok & r_tok
    if not common:
        return 0.0
    precision = len(common) / len(p_tok)
    recall = len(common) / len(r_tok)
    return 2 * precision * recall / (precision + recall)


def _best_f1_match(query: str, candidates: list[str]) -> tuple[float, str]:
    """在 candidates 中找与 query 最相似的条目，返回 (最高F1分, 最佳候选文本)。"""
    best_score, best_text = 0.0, ""
    for c in candidates:
        score = _token_f1(query, c)
        if score > best_score:
            best_score, best_text = score, c
    return best_score, best_text


# ---------------------------------------------------------------------------
# LLM-as-Judge
# ---------------------------------------------------------------------------

def _llm_judge(query: str, candidates: list[str], client: OpenAI, model: str) -> tuple[bool, str]:
    """
    用 LLM 判断 candidates 中是否存在语义上等价于 query 的条目。
    返回 (是否匹配, 裁判给出的理由)。
    """
    candidates_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(candidates))
    prompt = (
        f"参考条目（ground truth）：\n{query}\n\n"
        f"AI 生成列表（共 {len(candidates)} 条）：\n{candidates_text}\n\n"
        "判断：AI 生成列表中是否存在一条与参考条目语义等价的内容？"
        "语义等价指：即使措辞不同，但核心意图和覆盖范围相同。\n"
        "请仅输出 YES 或 NO，然后用一句话说明理由。"
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=100,
        messages=[
            {"role": "system", "content": "你是一名需求工程专家，负责判断两段需求描述是否语义等价。"},
            {"role": "user", "content": prompt},
        ],
    )
    answer = response.choices[0].message.content.strip()
    matched = answer.upper().startswith("YES")
    return matched, answer


# ---------------------------------------------------------------------------
# 三项评测函数
# ---------------------------------------------------------------------------

def _eval_requirements(
    result: PRDAnalysisResult,
    gt: dict,
    threshold: float,
    use_llm: bool,
    llm_client: Optional[OpenAI],
    llm_model: str,
    verbose: bool,
) -> dict:
    gt_items = gt["requirements"]["functional"] + gt["requirements"]["non_functional"]
    ai_texts = [r.description for r in result.requirements]

    matched, unmatched = [], []

    for item in gt_items:
        gt_text = item["description"]
        if use_llm and llm_client:
            is_match, reason = _llm_judge(gt_text, ai_texts, llm_client, llm_model)
            score = 1.0 if is_match else 0.0
            best_text = reason
        else:
            score, best_text = _best_f1_match(gt_text, ai_texts)
            is_match = score >= threshold

        entry = {"id": item["id"], "gt": gt_text, "best_match": best_text, "score": round(score, 3)}
        (matched if is_match else unmatched).append(entry)

    return {
        "matched": matched,
        "unmatched": unmatched,
        "recall": len(matched) / len(gt_items),
        "gt_total": len(gt_items),
        "matched_count": len(matched),
    }


def _eval_ambiguities(
    result: PRDAnalysisResult,
    gt: dict,
    threshold: float,
    use_llm: bool,
    llm_client: Optional[OpenAI],
    llm_model: str,
    verbose: bool,
) -> dict:
    gt_items = gt["ambiguities"]["items"]
    # 每条 AI 歧义生成三种候选文本：全拼接、仅 issue、仅 clarifying_question。
    # 避免拼接文本过长时 precision 被稀释导致 F1 虚低。
    ai_texts: list[str] = []
    for a in result.ambiguities:
        ai_texts.append(f"{a.location} {a.issue} {a.clarifying_question}")
        if a.issue:
            ai_texts.append(a.issue)
        if a.clarifying_question:
            ai_texts.append(a.clarifying_question)

    matched_e, unmatched_e = [], []
    matched_i, unmatched_i = [], []

    for item in gt_items:
        gt_text = f"{item['location']} {item['description']}"
        if use_llm and llm_client:
            is_match, reason = _llm_judge(gt_text, ai_texts, llm_client, llm_model)
            score = 1.0 if is_match else 0.0
            best_text = reason
        else:
            score, best_text = _best_f1_match(gt_text, ai_texts)
            is_match = score >= threshold

        entry = {"id": item["id"], "type": item["type"], "gt": item["description"],
                 "best_match": best_text, "score": round(score, 3)}
        if item["type"] == "explicit":
            (matched_e if is_match else unmatched_e).append(entry)
        else:
            (matched_i if is_match else unmatched_i).append(entry)

    total_e = len([x for x in gt_items if x["type"] == "explicit"])
    total_i = len([x for x in gt_items if x["type"] == "implicit"])
    matched_count = len(matched_e) + len(matched_i)

    return {
        "matched_explicit": matched_e,
        "unmatched_explicit": unmatched_e,
        "matched_implicit": matched_i,
        "unmatched_implicit": unmatched_i,
        "explicit_recall": len(matched_e) / total_e if total_e else 0.0,
        "implicit_recall": len(matched_i) / total_i if total_i else 0.0,
        "overall_recall": matched_count / len(gt_items) if gt_items else 0.0,
        "gt_total": len(gt_items),
        "matched_count": matched_count,
    }


def _eval_task_completeness(result: PRDAnalysisResult) -> dict:
    total = len(result.tasks)
    if total == 0:
        return {"completeness": 0.0, "total": 0, "complete_count": 0, "incomplete": []}

    complete_count = 0
    incomplete = []
    for task in result.tasks:
        missing = []
        if not task.title:
            missing.append("title")
        if not task.description:
            missing.append("description")
        if not task.acceptance_criteria:
            missing.append("acceptance_criteria")
        if not task.effort_estimate:
            missing.append("effort_estimate")
        if missing:
            incomplete.append({"task_id": task.id, "missing_fields": missing})
        else:
            complete_count += 1

    return {
        "completeness": complete_count / total,
        "total": total,
        "complete_count": complete_count,
        "incomplete": incomplete,
    }


# ---------------------------------------------------------------------------
# 输出渲染
# ---------------------------------------------------------------------------

def _status(score: float, target: float) -> str:
    return "[green]达标[/green]" if score >= target else "[red]未达标[/red]"


def _print_summary(req: dict, amb: dict, task: dict) -> None:
    gt = {
        "requirement_recall": {"target": 0.80},
        "ambiguity_explicit_recall": {"target": 0.80},
        "ambiguity_implicit_recall": {"target": 0.40},
        "ambiguity_overall_recall": {"target": 0.60},
        "task_completeness": {"target": 1.00},
    }

    table = Table(title="评测结果摘要", show_lines=True, expand=False)
    table.add_column("指标", min_width=20)
    table.add_column("得分", width=10)
    table.add_column("目标", width=10)
    table.add_column("AI输出数 / GT总数", width=18)
    table.add_column("状态", width=12)

    def pct(v: float) -> str:
        return f"{v * 100:.1f}%"

    table.add_row(
        "需求覆盖率",
        pct(req["recall"]),
        ">= 80%",
        f"{req['matched_count']} / {req['gt_total']}",
        _status(req["recall"], 0.80),
    )
    table.add_row(
        "歧义检测率（总）",
        pct(amb["overall_recall"]),
        ">= 60%",
        f"{amb['matched_count']} / {amb['gt_total']}",
        _status(amb["overall_recall"], 0.60),
    )
    table.add_row(
        "  显性歧义",
        pct(amb["explicit_recall"]),
        ">= 80%",
        f"{len(amb['matched_explicit'])} / {len(amb['matched_explicit']) + len(amb['unmatched_explicit'])}",
        _status(amb["explicit_recall"], 0.80),
    )
    table.add_row(
        "  隐性歧义",
        pct(amb["implicit_recall"]),
        ">= 40%",
        f"{len(amb['matched_implicit'])} / {len(amb['matched_implicit']) + len(amb['unmatched_implicit'])}",
        _status(amb["implicit_recall"], 0.40),
    )
    table.add_row(
        "任务完整度",
        pct(task["completeness"]),
        "= 100%",
        f"{task['complete_count']} / {task['total']}",
        _status(task["completeness"], 1.00),
    )
    try:
        console.print(table)
    except Exception:
        # Fallback: plain text when terminal can't render Rich table
        console.print("[bold]评测结果摘要[/bold]", markup=True)
        console.print(f"  需求覆盖率       : {pct(req['recall'])} (目标>=80%) - {req['matched_count']}/{req['gt_total']}", markup=False)
        console.print(f"  歧义检测率(总)   : {pct(amb['overall_recall'])} (目标>=60%) - {amb['matched_count']}/{amb['gt_total']}", markup=False)
        console.print(f"    显性歧义       : {pct(amb['explicit_recall'])} (目标>=80%)", markup=False)
        console.print(f"    隐性歧义       : {pct(amb['implicit_recall'])} (目标>=40%)", markup=False)
        console.print(f"  任务完整度       : {pct(task['completeness'])} (目标=100%) - {task['complete_count']}/{task['total']}", markup=False)


def _print_task_only_summary(task: dict) -> None:
    """无 ground truth 时只展示任务完整度。"""
    table = Table(title="评测结果摘要（无 GT，仅任务完整度）", show_lines=True, expand=False)
    table.add_column("指标", min_width=20)
    table.add_column("得分", width=10)
    table.add_column("目标", width=10)
    table.add_column("任务数", width=10)
    table.add_column("状态", width=12)
    pct = lambda v: f"{v * 100:.1f}%"
    table.add_row(
        "任务完整度",
        pct(task["completeness"]),
        "= 100%",
        f"{task['complete_count']} / {task['total']}",
        _status(task["completeness"], 1.00),
    )
    try:
        console.print(table)
    except Exception:
        console.print(f"  任务完整度: {pct(task['completeness'])} ({task['complete_count']}/{task['total']})", markup=False)


def _print_verbose_requirements(req: dict) -> None:
    console.print("\n[bold]需求匹配详情[/bold]")
    for m in req["matched"]:
        gt_short = escape(m['gt'][:60]) + ("..." if len(m['gt']) > 60 else "")
        console.print(f"  [green]+[/green] [{escape(m['id'])}] {gt_short}")
        if isinstance(m["score"], float):
            console.print(f"       F1={m['score']:.2f}  ->  {escape(m['best_match'][:60])}", markup=False)
    for u in req["unmatched"]:
        gt_short = escape(u['gt'][:60]) + ("..." if len(u['gt']) > 60 else "")
        console.print(f"  [red]-[/red] [{escape(u['id'])}] {gt_short}")
        if isinstance(u["score"], float):
            console.print(f"       最高F1={u['score']:.2f}", markup=False)


def _print_verbose_ambiguities(amb: dict) -> None:
    console.print("\n[bold]歧义匹配详情[/bold]")
    console.print("[bold yellow]显性歧义（Open Questions）[/bold yellow]")
    for m in amb["matched_explicit"]:
        console.print(f"  [green]+[/green] [{escape(m['id'])}] {escape(m['gt'][:55])}")
    for u in amb["unmatched_explicit"]:
        console.print(f"  [red]-[/red] [{escape(u['id'])}] {escape(u['gt'][:55])}")

    console.print("[bold yellow]隐性歧义[/bold yellow]")
    for m in amb["matched_implicit"]:
        console.print(f"  [green]+[/green] [{escape(m['id'])}] {escape(m['gt'][:55])}")
    for u in amb["unmatched_implicit"]:
        console.print(f"  [red]-[/red] [{escape(u['id'])}] {escape(u['gt'][:55])}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@app.command()
def main(
    prd: Path = typer.Option(DEFAULT_PRD_PATH, "--prd", help="待评测的 PRD 文件路径"),
    ground_truth: Optional[Path] = typer.Option(None, "--ground-truth", "--gt", help="ground truth JSON 路径；不提供则仅评测任务完整度"),
    threshold: float = typer.Option(0.25, "--threshold", help="token-F1 回退阈值（仅 --no-llm-judge 时生效）"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="显示每条匹配/未匹配详情"),
    save: Optional[Path] = typer.Option(None, "--save", help="将完整报告保存为 JSON 文件"),
    llm_judge: bool = typer.Option(True, "--llm-judge/--no-llm-judge", help="用 LLM 语义裁判（默认开启）；--no-llm-judge 回退到 token-F1"),
    model: str = typer.Option("deepseek-v4-flash", "--model", help="LLM-as-Judge 使用的模型"),
) -> None:
    """对比 AI 分析结果与 ground truth，输出评测指标。不提供 --gt 时仅评测任务完整度。"""

    FIXTURES = Path("tests/fixtures")

    def _resolve(p: Path) -> Path:
        """如果路径不存在，自动在 tests/fixtures/ 下查找同名文件。"""
        if p.exists():
            return p
        candidate = FIXTURES / p.name
        if candidate.exists():
            return candidate
        return p  # 原路径，留给后续报错

    prd = _resolve(prd)
    if not prd.exists():
        console.print(f"[red]找不到 PRD 文件：{prd}（也在 tests/fixtures/ 下找不到）[/red]")
        raise typer.Exit(1)

    # ground truth 自动发现：显式指定 > 同目录下 {stem}_ground_truth.json > 无
    gt: Optional[dict] = None
    if ground_truth is not None:
        ground_truth = _resolve(ground_truth)
        if not ground_truth.exists():
            console.print(f"[red]找不到 ground truth 文件：{ground_truth}[/red]")
            raise typer.Exit(1)
        gt = json.loads(ground_truth.read_text(encoding="utf-8"))
    else:
        # 按命名规则自动查找：points_prd.md → points_prd_ground_truth.json
        auto_gt = prd.parent / f"{prd.stem}_ground_truth.json"
        if auto_gt.exists():
            gt = json.loads(auto_gt.read_text(encoding="utf-8"))
            ground_truth = auto_gt
            console.print(f"[dim]自动加载 GT：{auto_gt}[/dim]")

    has_gt = gt is not None
    gt_label = str(ground_truth) if has_gt else "无（仅评测任务完整度）"

    # --save 未指定时，默认保存为 {prd_stem}_eval_{时间戳}.json，避免覆盖历史结果
    if save is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        save = Path(f"{prd.stem}_eval_{ts}.json")

    console.print(
        Panel(
            f"[bold blue]PRD 分析效果评测[/bold blue]\n"
            f"PRD：[cyan]{prd}[/cyan]\n"
            f"GT ：[cyan]{gt_label}[/cyan]\n"
            f"匹配：{'[magenta]LLM-as-Judge[/magenta]' if llm_judge else f'token-F1（阈值={threshold}）'}",
            expand=False,
        )
    )

    # 初始化 LLM 客户端（与 PRDAnalyzer 共用同一 DASHSCOPE_API_KEY）
    llm_client: Optional[OpenAI] = None
    if llm_judge:
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        if api_key:
            llm_client = OpenAI(api_key=api_key, base_url=BAILIAN_BASE_URL)
        else:
            console.print("[yellow]未找到 DASHSCOPE_API_KEY，自动回退到 token-F1 匹配[/yellow]")
            llm_judge = False

    # 调用 AI 分析
    prd_text = prd.read_text(encoding="utf-8")
    with console.status("[bold green]调用 AI 分析 PRD（约 30 秒）..."):
        try:
            analyzer = PRDAnalyzer()
            result = analyzer.analyze(prd_text)
        except Exception as exc:
            console.print(f"[red]AI 分析失败：{escape(str(exc))}[/red]")
            raise typer.Exit(1)

    console.print(
        f"\n[green]AI 分析完成[/green]  "
        f"需求 [cyan]{result.summary.total_requirements}[/cyan] 条 / "
        f"歧义 [yellow]{result.summary.ambiguity_count}[/yellow] 条 / "
        f"任务 [green]{result.summary.total_tasks}[/green] 个"
    )

    # 评测
    judge_label = "LLM裁判" if llm_judge else "token-F1"
    with console.status(f"[bold green]运行评测（{judge_label}）..."):
        task_result = _eval_task_completeness(result)
        if has_gt:
            req_result = _eval_requirements(result, gt, threshold, llm_judge, llm_client, model, verbose)
            amb_result = _eval_ambiguities(result, gt, threshold, llm_judge, llm_client, model, verbose)

    console.print()
    if has_gt:
        _print_summary(req_result, amb_result, task_result)
    else:
        _print_task_only_summary(task_result)

    if verbose and has_gt:
        _print_verbose_requirements(req_result)
        _print_verbose_ambiguities(amb_result)

    if verbose and task_result["incomplete"]:
        console.print("\n[bold]不完整任务[/bold]")
        for t in task_result["incomplete"]:
            console.print(f"  [red]-[/red] {escape(str(t['task_id']))}  缺少字段：{t['missing_fields']}")

    # 保存 JSON 报告
    if save:
        report: dict = {
            "config": {
                "prd": str(prd),
                "ground_truth": str(ground_truth) if has_gt else None,
                "method": "llm-judge" if llm_judge else "token-f1",
                "threshold": threshold if not llm_judge else None,
                "model": model if llm_judge else None,
            },
            "ai_output_summary": {
                "requirements": result.summary.total_requirements,
                "ambiguities": result.summary.ambiguity_count,
                "tasks": result.summary.total_tasks,
            },
            "task_completeness": task_result,
            "scores": {"task_completeness": round(task_result["completeness"], 4)},
        }
        if has_gt:
            report["requirement_recall"] = req_result
            report["ambiguity_recall"] = amb_result
            report["scores"].update({
                "requirement_recall": round(req_result["recall"], 4),
                "ambiguity_overall_recall": round(amb_result["overall_recall"], 4),
                "ambiguity_explicit_recall": round(amb_result["explicit_recall"], 4),
                "ambiguity_implicit_recall": round(amb_result["implicit_recall"], 4),
            })
        save.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"\n[green]完整报告已保存 → {save}[/green]")


if __name__ == "__main__":
    app()
