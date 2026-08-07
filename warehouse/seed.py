"""Deterministic generator for the retail warehouse.

Everything comes off one seeded Random. The same seed has to produce the same database
byte for byte, otherwise no number measured against it means anything on a later day.
`warehouse/fingerprint.py` is what proves that claim rather than asserting it.
"""

import datetime as dt
import random

SEED = 20261007

COUNTRIES = ["US", "GB", "DE", "FR", "CA", "AU", "NL", "ES"]
TIERS = ["bronze", "silver", "gold", "platinum"]
DEPARTMENTS = ["apparel", "home", "electronics", "grocery", "outdoor"]
STATUSES = ["completed", "completed", "completed", "completed", "shipped", "cancelled"]
CARRIERS = ["fleetline", "postnord", "grayhaul", "swiftbox"]
METHODS = ["card", "card", "card", "paypal", "bank_transfer", "gift_card"]
DEVICES = ["mobile", "desktop", "tablet"]
REASONS = ["damaged", "wrong_size", "not_as_described", "changed_mind", "late_delivery"]
SEVERITIES = ["low", "medium", "high", "critical"]
TOPICS = ["delivery", "billing", "product_quality", "account", "returns"]
ROLES = ["associate", "supervisor", "manager", "stock_clerk"]

START = dt.date(2024, 1, 1)
DAYS = 731  # 2024 and 2025, 2024 is a leap year


def date_key(d):
    return d.year * 10000 + d.month * 100 + d.day


def build(rng=None):
    """Return every table as a list of tuples, in insert order."""
    rng = rng or random.Random(SEED)
    out = {}

    dates = []
    for i in range(DAYS):
        d = START + dt.timedelta(days=i)
        dow = d.isoweekday()
        dates.append((
            date_key(d), d, dow, d.strftime("%A"),
            int(d.strftime("%V")), d.month, d.strftime("%B"),
            (d.month - 1) // 3 + 1, d.year, dow >= 6,
        ))
    out["dim_date"] = dates

    customers = []
    for cid in range(1, 4001):
        signup = START + dt.timedelta(days=rng.randrange(DAYS))
        customers.append((
            cid, "user%04d@example.invalid" % cid, "Customer %04d" % cid, signup,
            rng.choice(COUNTRIES), rng.choice(["Leeds", "Austin", "Lyon", "Utrecht", None]),
            rng.choice(TIERS), rng.random() > 0.12, rng.random() > 0.4,
        ))
    out["dim_customer"] = customers

    categories = []
    for i in range(1, 21):
        categories.append((i, "category_%02d" % i, DEPARTMENTS[(i - 1) % len(DEPARTMENTS)]))
    out["dim_category"] = categories

    suppliers = []
    for i in range(1, 41):
        suppliers.append((i, "supplier_%02d" % i, rng.choice(COUNTRIES), rng.randrange(3, 45)))
    out["dim_supplier"] = suppliers

    products = []
    for pid in range(1, 801):
        cost = round(rng.uniform(2.0, 260.0), 2)
        products.append((
            pid, "SKU-%05d" % pid, "product %03d" % pid,
            rng.randrange(1, 21), rng.randrange(1, 41),
            round(cost * rng.uniform(1.25, 2.6), 2), cost,
            rng.random() < 0.09,
        ))
    out["dim_product"] = products

    bridge = []
    for p in products:
        bridge.append((p[0], p[3], True))
        if rng.random() < 0.5:
            alt = rng.randrange(1, 21)
            if alt != p[3]:
                bridge.append((p[0], alt, False))
    out["bridge_product_category"] = bridge

    stores = []
    for sid in range(1, 26):
        stores.append((
            sid, "store_%02d" % sid, rng.choice(COUNTRIES),
            rng.choice(["Leeds", "Austin", "Lyon", "Utrecht", "Bristol"]),
            dt.date(2015, 1, 1) + dt.timedelta(days=rng.randrange(3000)),
            rng.randrange(400, 4200),
        ))
    out["dim_store"] = stores

    out["dim_channel"] = [
        (1, "web", True), (2, "mobile_app", True),
        (3, "in_store", False), (4, "phone", False),
    ]

    promos = []
    for i in range(1, 13):
        s = START + dt.timedelta(days=rng.randrange(DAYS - 30))
        promos.append((i, "PROMO%02d" % i, round(rng.uniform(5, 35), 2), s, s + dt.timedelta(days=rng.randrange(7, 30))))
    out["dim_promotion"] = promos

    employees = []
    for eid in range(1, 301):
        employees.append((
            eid, "Employee %03d" % eid,
            rng.randrange(1, 26) if rng.random() > 0.05 else None,
            rng.choice(ROLES),
            dt.date(2018, 1, 1) + dt.timedelta(days=rng.randrange(2800)),
            round(rng.uniform(24000, 96000), 2),
        ))
    out["dim_employee"] = employees

    headers, lines, payments, shipments, returns = [], [], [], [], []
    line_id = 0
    payment_id = 0
    shipment_id = 0
    return_id = 0
    # 4000 customers do not all order. The unordered tail is what q22 is about.
    ordering_customers = [c[0] for c in customers if rng.random() < 0.86]

    for oid in range(100001, 125001):
        cust = rng.choice(ordering_customers)
        d = START + dt.timedelta(days=rng.randrange(DAYS))
        channel = rng.randrange(1, 5)
        store = rng.randrange(1, 26) if channel in (3, 4) else None
        promo = rng.randrange(1, 13) if rng.random() < 0.22 else None
        status = rng.choice(STATUSES)
        ts = dt.datetime.combine(d, dt.time(rng.randrange(24), rng.randrange(60), rng.randrange(60)))

        n_lines = rng.choice([1, 1, 2, 2, 3, 4, 5])
        line_net = 0.0
        for _ in range(n_lines):
            line_id += 1
            prod = products[rng.randrange(800)]
            qty = rng.choice([1, 1, 1, 2, 3])
            price = float(prod[5])
            disc = round(price * qty * rng.choice([0.0, 0.0, 0.0, 0.1, 0.2]), 2)
            net = round(price * qty - disc, 2)
            line_net += net
            lines.append((line_id, oid, prod[0], qty, price, disc, net))
            # returns hang off a line, not off an order
            if status == "completed" and rng.random() < 0.048:
                return_id += 1
                rd = d + dt.timedelta(days=rng.randrange(2, 40))
                if rd < START + dt.timedelta(days=DAYS):
                    returns.append((return_id, line_id, date_key(rd), rng.choice(REASONS),
                                    rng.randrange(1, qty + 1), round(net * rng.uniform(0.4, 1.0), 2)))
                else:
                    return_id -= 1

        # header discount applied on top of the lines, so order_total != sum(net_amount)
        header_disc = round(line_net * (float(promos[promo - 1][2]) / 100.0), 2) if promo else 0.0
        total = round(line_net - header_disc, 2)
        headers.append((oid, cust, store, channel, promo, date_key(d), ts, status, total, "USD"))

        if status != "cancelled":
            payment_id += 1
            payments.append((payment_id, oid, ts + dt.timedelta(minutes=rng.randrange(1, 90)),
                             rng.choice(METHODS), total, rng.random() > 0.02))
        # in-store and phone orders are collected, not shipped. Without this the shipment
        # count comes out exactly equal to the payment count, because "not cancelled" and
        # "completed or shipped" are the same predicate on this status list.
        if status in ("completed", "shipped") and channel in (1, 2):
            shipment_id += 1
            sh = ts + dt.timedelta(days=rng.randrange(1, 4))
            deliv = sh + dt.timedelta(days=rng.randrange(1, 9)) if status == "completed" else None
            shipments.append((shipment_id, oid, sh, deliv, rng.choice(CARRIERS), round(rng.uniform(2.5, 24.0), 2)))

    out["fct_order_header"] = headers
    out["fct_order_line"] = lines
    out["fct_payment"] = payments
    out["fct_shipment"] = shipments
    out["fct_return"] = returns

    snaps = []
    snap_products = [p[0] for p in products[:150]]
    for week in range(12):
        d = START + dt.timedelta(days=600 + week * 7)
        for pid in snap_products:
            for sid in range(1, 21):
                snaps.append((date_key(d), pid, sid, rng.randrange(0, 140), rng.randrange(0, 40)))
    out["fct_inventory_snapshot"] = snaps

    sessions = []
    for sid in range(1, 40001):
        cust = rng.choice(ordering_customers) if rng.random() < 0.55 else None
        ts = dt.datetime.combine(START + dt.timedelta(days=rng.randrange(DAYS)),
                                 dt.time(rng.randrange(24), rng.randrange(60)))
        sessions.append((sid, cust, ts, rng.randrange(5, 2400), rng.randrange(1, 40),
                         rng.choice(DEVICES), rng.random() < 0.11))
    out["fct_web_session"] = sessions

    tickets = []
    for tid in range(1, 3001):
        opened = dt.datetime.combine(START + dt.timedelta(days=rng.randrange(DAYS)),
                                     dt.time(rng.randrange(24), rng.randrange(60)))
        closed = opened + dt.timedelta(hours=rng.randrange(1, 200)) if rng.random() > 0.14 else None
        tickets.append((tid, rng.choice(ordering_customers),
                        rng.randrange(100001, 125001) if rng.random() < 0.6 else None,
                        opened, closed, rng.choice(SEVERITIES), rng.choice(TOPICS)))
    out["fct_support_ticket"] = tickets

    return out
