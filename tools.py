"""Deterministic verification and routing tools for Công ty Minh An B2B Sales AI Agent."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def normalize_text(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics for resilient SKU matching."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d")


def load_master_data(data_path: str | Path) -> dict[str, Any]:
    """Load Minh An catalog, sales team, and policy configuration."""
    return json.loads(Path(data_path).read_text(encoding="utf-8"))


@dataclass
class VerifiedLineItem:
    line_no: int
    sku: str
    name: str
    unit: str
    quantity: int
    unit_price_vnd: int
    line_total_vnd: int
    stock_available: int
    shortfall: int
    feasible_days: int
    stock_status: str


def check_completeness_gate(extracted: dict[str, Any]) -> list[str]:
    """Step 2: Verify the 4 mandatory groups before creating an opportunity."""
    missing: list[str] = []
    items = extracted.get("items") or []
    if not items or any(it.get("quantity") in (None, 0) for it in items):
        missing.append("Danh sách sản phẩm/dịch vụ & số lượng cụ thể")
    if not extracted.get("budget_vnd"):
        missing.append("Ngân sách tổng dự kiến (VND)")
    if not extracted.get("requested_deadline_days"):
        missing.append("Thời hạn triển khai / ngày bàn giao cụ thể")
    if not extracted.get("approver_identified"):
        missing.append("Người phê duyệt / đầu mối quyết định ngân sách")
    return missing


def assign_sales_owner(
    sales_team: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Step 4: Assign 1 of 6 NVKD balancing workload and product specialty."""
    catalog_map = {c["sku"]: c for c in catalog}
    primary_category = ""
    if items and items[0].get("sku") in catalog_map:
        primary_category = catalog_map[items[0]["sku"]]["category"]

    def score(rep: dict[str, Any]) -> int:
        spec = normalize_text(rep["specialty"])
        bonus = 0
        if primary_category == "Server" and "server" in spec:
            bonus = -2
        elif primary_category in ("Network", "Security") and ("mang" in spec or "bao mat" in spec):
            bonus = -2
        elif primary_category == "Endpoint" and ("laptop" in spec or "dau cuoi" in spec):
            bonus = -2
        elif primary_category == "Service" and ("dich vu" in spec or "trien khai" in spec):
            bonus = -2
        return int(rep["active_deals"]) + bonus

    return min(sales_team, key=score)


def verify_inventory_and_pricing(
    items: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    """Step 5: Lock pricing to active price list and calculate Ops lead time."""
    catalog_map = {c["sku"]: c for c in catalog}
    verified: list[VerifiedLineItem] = []
    subtotal = 0
    max_feasible_days = 0
    ops_issues: list[str] = []

    for idx, item in enumerate(items, start=1):
        sku = item.get("sku")
        if sku not in catalog_map:
            raw_norm = normalize_text(item.get("raw_name", ""))
            for cat in catalog:
                candidates = [cat["name"], *cat.get("aliases", [])]
                if any(normalize_text(c) in raw_norm or raw_norm in normalize_text(c) for c in candidates):
                    sku = cat["sku"]
                    break
        if sku not in catalog_map:
            continue

        cat = catalog_map[sku]
        qty = int(item.get("quantity") or 1)
        unit_price = int(cat["current_price_vnd"])
        line_total = unit_price * qty
        subtotal += line_total

        stock_avail = int(cat["stock_available"])
        shortfall = max(0, qty - stock_avail)
        if shortfall == 0:
            feasible_days = int(cat["deploy_lead_time_days"])
            stock_status = f"Đủ tồn kho ({stock_avail}/{qty})"
        else:
            feasible_days = int(cat["inbound_eta_days"]) + int(cat["deploy_lead_time_days"])
            stock_status = f"Thiếu {shortfall} {cat['unit']} (Tồn: {stock_avail}, Nhập sau {cat['inbound_eta_days']} ngày)"
            ops_issues.append(f"{cat['name']}: còn {stock_avail}, cần {qty} (sớm nhất {feasible_days} ngày)")

        max_feasible_days = max(max_feasible_days, feasible_days)
        verified.append(
            VerifiedLineItem(
                line_no=idx,
                sku=cat["sku"],
                name=cat["name"],
                unit=cat["unit"],
                quantity=qty,
                unit_price_vnd=unit_price,
                line_total_vnd=line_total,
                stock_available=stock_avail,
                shortfall=shortfall,
                feasible_days=feasible_days,
                stock_status=stock_status,
            )
        )

    return {
        "line_items": [v.__dict__ for v in verified],
        "subtotal_vnd": subtotal,
        "max_feasible_days": max_feasible_days,
        "ops_issues": ops_issues,
    }


def evaluate_authority_policy(
    final_total_vnd: int,
    discount_pct: float,
    mentions_old_price: bool,
    policy: dict[str, Any],
) -> list[str]:
    """Step 6/7: Determine whether proposal requires Sales Manager approval."""
    reasons: list[str] = []
    max_rep_discount = float(policy["sales_rep_max_discount_pct"])
    max_order_total = int(policy["auto_escalate_if_total_over_vnd"])

    if discount_pct > max_rep_discount:
        reasons.append(f"Chiết khấu {discount_pct}% vượt thẩm quyền NVKD (tối đa {max_rep_discount}%)")
    if final_total_vnd > max_order_total:
        reasons.append(f"Tổng đơn hàng vượt ngưỡng {max_order_total:,} VND")
    if mentions_old_price:
        reasons.append("Khách hàng từng đề nghị áp dụng bảng giá cũ")
    return reasons

