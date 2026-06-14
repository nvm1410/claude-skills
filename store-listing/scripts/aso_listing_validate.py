#!/usr/bin/env python3
"""Deterministic validator for the keyword-driven store-listing fields.

Holds the proposed per-locale fields (app name, iOS subtitle, iOS keyword field,
Android short description) and asserts the rules from docs/aso-keyword-plan.md
before they are written into the listing docs:

  * char limits per field/store (App Store + Play hard limits);
  * iOS no-word-duplication across name / subtitle / keyword field;
  * keyword field: comma-separated, no spaces only between tokens is allowed for
    multi-word native terms, <=100 chars, no brand names;
  * iOS truthfulness: no background/notification/real-time/automatic/instant
    claims and no $49.99 intro price in any iOS-facing field.

Run: python tool/aso_listing_validate.py   (exit 0 = all green)
"""
from __future__ import annotations
import re, sys

# Brand / trademark blocklist (single tokens) — keyword fields must avoid these.
BRANDS = {
    "expensify","everydollar","rocket","mint","ynab","monzo","revolut","wise",
    "klarna","deutschlandcard","finanzguru","wiso","moneycontrol","walmart",
    "snapdeal","oyo","skyscanner","wego","fabhotels","scb","kbank","evernote",
    "moneytree","zaim","vpbank","tomi","misa","mobills","organizze","bankin",
    "linxo","fortuneo","cofidis","tricount","coinkeeper","paypal","momo",
    "zalopay","gcash","albo",
}
# iOS-forbidden truthfulness terms (substring, case-insensitive).
IOS_FORBIDDEN = ["background","notification","real-time","realtime","automatic",
                 "instant","49.99"]

# Per-locale proposed fields. name/short used on BOTH stores (localized);
# subtitle + keywords are iOS-only.
FIELDS = {
 "en": {
   "name": "Kachak: AI Expense Tracker",
   "subtitle": "Receipt Scanner & Budgets",
   "keywords": "money,spending,bills,planner,manager,finance,wallet,saving,recurring,cashflow,cards,tax,income",
   "short": "Snap a payment screenshot and AI logs the expense. Budgets, insights, synced.",
 },
 "vi": {
   "name": "Kachak: Quản Lý Chi Tiêu",
   "subtitle": "Quét hóa đơn & ngân sách AI",
   "keywords": "tài chính,tiết kiệm,thu nhập,ví tiền,dòng tiền,theo dõi,hằng ngày,báo cáo,danh mục,tiền mặt",
   "short": "Chụp hóa đơn, AI ghi chi tiêu cho bạn. Ngân sách, thống kê, đồng bộ đa thiết bị.",
 },
 "es": {
   "name": "Kachak: Escáner de Gastos",
   "subtitle": "Presupuesto y dinero con IA",
   "keywords": "finanzas,control,ingresos,recibos,ahorro,billetera,facturas,moneda,mensual,cartera,diario",
   "short": "Captura un recibo y la IA registra el gasto. Presupuestos e informes.",
 },
 "pt": {
   "name": "Kachak: Controle de Gastos",
   "subtitle": "Recibos e orçamento com IA",
   "keywords": "finanças,dinheiro,despesas,economias,cashback,rastreador,contas,scanner,carteira,mensal",
   "short": "Fotografe um recibo e a IA registra o gasto. Orçamentos e relatórios.",
 },
 "de": {
   "name": "Kachak: KI Ausgaben Scanner",
   "subtitle": "Belege & Haushaltsbuch",
   "keywords": "finanzen,steuer,konten,geld,sparen,budget,kassenbon,dokumente,planer,reisekosten,kosten",
   "short": "Beleg fotografieren, KI bucht die Ausgabe. Budget, Einblicke, Sync.",
 },
 "fr": {
   "name": "Kachak: Scanner de Reçus",
   "subtitle": "Dépenses & budget par IA",
   "keywords": "finances,argent,compte,suivi,cartes,carnet,frais,épargne,revenus,mensuel,facture,monnaie",
   "short": "Photographiez un reçu et l'IA enregistre la dépense. Budgets, insights, sync.",
 },
 "ja": {
   "name": "Kachak: AIレシート家計簿",
   "subtitle": "支出管理をシンプルに",
   "keywords": "予算,貯金,節約,収入,お金,家計,カテゴリ,定期,通貨,毎日,収支,カード,簡単,銀行,通帳,円",
   "short": "レシートを撮影するだけでAIが支出を記録。予算管理・家計分析、デバイス間同期対応。",
 },
 "hi": {
   "name": "Kachak: AI खर्च ट्रैकर",
   "subtitle": "बजट और रसीद स्कैनर",
   "keywords": "पैसा,बचत,वित्त,आय,लेनदेन,मासिक,बटुआ,बिल,रिपोर्ट,मुद्रा,दैनिक,नकद",
   "short": "रसीद की फोटो लें, AI खर्च दर्ज करे। बजट, विश्लेषण, सिंक — सब एक जगह।",
 },
 "id": {
   "name": "Kachak: Pelacak Keuangan AI",
   "subtitle": "Struk jadi catatan, AI",
   "keywords": "anggaran,pengeluaran,uang,tabungan,dompet,pendapatan,tagihan,bulanan,scanner,laporan,harian",
   "short": "Foto struk dan AI mencatat pengeluaran. Anggaran, wawasan, sinkron.",
 },
 "th": {
   "name": "Kachak: AI สแกนใบเสร็จ",
   "subtitle": "จัดการเงินและงบประมาณ",
   "keywords": "รายจ่าย,การเงิน,เงิน,ออมเงิน,รายได้,กระเป๋าเงิน,บิล,รายเดือน,ภาษี,บันทึก,รายงาน,สกุลเงิน",
   "short": "ถ่ายรูปใบเสร็จ AI บันทึกรายจ่าย งบประมาณ วิเคราะห์ ซิงค์ทุกอุปกรณ์",
 },
}

LIM = {"name": 30, "subtitle": 30, "keywords": 100, "short": 80}

def tokens(s: str):
    return {t for t in re.split(r"[\s,&]+", s.lower()) if t}

def main():
    bad = 0
    for loc, f in FIELDS.items():
        print(f"\n== {loc} ==")
        for k in ("name","subtitle","keywords","short"):
            n = len(f[k])
            ok = n <= LIM[k]
            flag = "" if ok else "  <-- OVER LIMIT"
            if not ok: bad += 1
            print(f"  {k:9} {n:>3}/{LIM[k]}{flag}")
        # iOS no-dup across name/subtitle/keywords
        ntok, stok = tokens(f["name"]), tokens(f["subtitle"])
        ktoks = [t for t in re.split(r"[,]", f["keywords"]) for t in re.split(r"\s+", t.strip()) if t]
        dup = sorted((set(t.lower() for t in ktoks) & (ntok | stok)) - {"ai","ia","ki"})
        if dup:
            print(f"  DUP keyword<->name/subtitle: {dup}"); bad += 1
        # brand check in keyword field
        kbrand = sorted(set(t.lower() for t in ktoks) & BRANDS)
        if kbrand:
            print(f"  BRAND in keywords: {kbrand}"); bad += 1
        # iOS truthfulness on name/subtitle/keywords
        ios_blob = " ".join([f["name"], f["subtitle"], f["keywords"]]).lower()
        forb = [w for w in IOS_FORBIDDEN if w in ios_blob]
        if forb:
            print(f"  iOS-forbidden term: {forb}"); bad += 1
    print(f"\n{'ALL GREEN' if bad==0 else str(bad)+' VIOLATIONS'}")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
