-- Retail warehouse used by the text-to-SQL agent.
-- Written for DuckDB. warehouse/schema_snowflake.sql carries the same model in
-- Snowflake types, because there is no Snowflake account to verify against yet.
--
-- The table count is meant to be awkward rather than large. Eighteen tables render in
-- 2,716 characters, which fits in any prompt worth using. The retrieval layer
-- measured retrieval against that and found it does not pay here. See docs/adr-0005.

CREATE SCHEMA IF NOT EXISTS retail;

CREATE TABLE retail.dim_date (
    date_key        INTEGER PRIMARY KEY,
    full_date       DATE NOT NULL,
    day_of_week     SMALLINT NOT NULL,
    day_name        VARCHAR NOT NULL,
    week_of_year    SMALLINT NOT NULL,
    month_number    SMALLINT NOT NULL,
    month_name      VARCHAR NOT NULL,
    quarter_number  SMALLINT NOT NULL,
    year_number     SMALLINT NOT NULL,
    is_weekend      BOOLEAN NOT NULL
);

CREATE TABLE retail.dim_customer (
    customer_id      INTEGER PRIMARY KEY,
    customer_email   VARCHAR NOT NULL,
    full_name        VARCHAR NOT NULL,
    signup_date      DATE NOT NULL,
    country_code     VARCHAR NOT NULL,
    city             VARCHAR,
    loyalty_tier     VARCHAR NOT NULL,
    is_active        BOOLEAN NOT NULL,
    marketing_opt_in BOOLEAN NOT NULL
);

CREATE TABLE retail.dim_category (
    category_id     INTEGER PRIMARY KEY,
    category_name   VARCHAR NOT NULL,
    department      VARCHAR NOT NULL
);

CREATE TABLE retail.dim_supplier (
    supplier_id     INTEGER PRIMARY KEY,
    supplier_name   VARCHAR NOT NULL,
    country_code    VARCHAR NOT NULL,
    lead_time_days  SMALLINT NOT NULL
);

CREATE TABLE retail.dim_product (
    product_id      INTEGER PRIMARY KEY,
    sku             VARCHAR NOT NULL,
    product_name    VARCHAR NOT NULL,
    category_id     INTEGER NOT NULL,
    supplier_id     INTEGER NOT NULL,
    list_price      DECIMAL(10,2) NOT NULL,
    unit_cost       DECIMAL(10,2) NOT NULL,
    is_discontinued BOOLEAN NOT NULL
);

CREATE TABLE retail.bridge_product_category (
    product_id      INTEGER NOT NULL,
    category_id     INTEGER NOT NULL,
    is_primary      BOOLEAN NOT NULL
);

CREATE TABLE retail.dim_store (
    store_id        INTEGER PRIMARY KEY,
    store_name      VARCHAR NOT NULL,
    country_code    VARCHAR NOT NULL,
    city            VARCHAR NOT NULL,
    opened_date     DATE NOT NULL,
    floor_area_sqm  INTEGER NOT NULL
);

CREATE TABLE retail.dim_channel (
    channel_id      INTEGER PRIMARY KEY,
    channel_name    VARCHAR NOT NULL,
    is_online       BOOLEAN NOT NULL
);

CREATE TABLE retail.dim_promotion (
    promotion_id    INTEGER PRIMARY KEY,
    promotion_code  VARCHAR NOT NULL,
    discount_pct    DECIMAL(5,2) NOT NULL,
    starts_on       DATE NOT NULL,
    ends_on         DATE NOT NULL
);

CREATE TABLE retail.dim_employee (
    employee_id     INTEGER PRIMARY KEY,
    full_name       VARCHAR NOT NULL,
    store_id        INTEGER,
    role_name       VARCHAR NOT NULL,
    hired_date      DATE NOT NULL,
    annual_salary   DECIMAL(10,2) NOT NULL
);

-- order_total is stored on the header and is NOT the sum of the lines. It is the sum of
-- the lines minus the header level discount. A join that sums net_amount and compares it
-- to order_total will disagree, on purpose. Static validation has to catch that class.
CREATE TABLE retail.fct_order_header (
    order_id        BIGINT PRIMARY KEY,
    customer_id     INTEGER NOT NULL,
    store_id        INTEGER,
    channel_id      INTEGER NOT NULL,
    promotion_id    INTEGER,
    order_date_key  INTEGER NOT NULL,
    order_ts        TIMESTAMP NOT NULL,
    order_status    VARCHAR NOT NULL,
    order_total     DECIMAL(12,2) NOT NULL,
    currency_code   VARCHAR NOT NULL
);

CREATE TABLE retail.fct_order_line (
    order_line_id   BIGINT PRIMARY KEY,
    order_id        BIGINT NOT NULL,
    product_id      INTEGER NOT NULL,
    quantity        INTEGER NOT NULL,
    unit_price      DECIMAL(10,2) NOT NULL,
    discount_amount DECIMAL(10,2) NOT NULL,
    net_amount      DECIMAL(12,2) NOT NULL
);

CREATE TABLE retail.fct_payment (
    payment_id      BIGINT PRIMARY KEY,
    order_id        BIGINT NOT NULL,
    paid_ts         TIMESTAMP NOT NULL,
    payment_method  VARCHAR NOT NULL,
    amount          DECIMAL(12,2) NOT NULL,
    is_captured     BOOLEAN NOT NULL
);

CREATE TABLE retail.fct_shipment (
    shipment_id     BIGINT PRIMARY KEY,
    order_id        BIGINT NOT NULL,
    shipped_ts      TIMESTAMP,
    delivered_ts    TIMESTAMP,
    carrier_name    VARCHAR NOT NULL,
    ship_cost       DECIMAL(10,2) NOT NULL
);

CREATE TABLE retail.fct_return (
    return_id       BIGINT PRIMARY KEY,
    order_line_id   BIGINT NOT NULL,
    returned_date_key INTEGER NOT NULL,
    reason_code     VARCHAR NOT NULL,
    quantity        INTEGER NOT NULL,
    return_amount   DECIMAL(12,2) NOT NULL
);

CREATE TABLE retail.fct_inventory_snapshot (
    snapshot_date_key INTEGER NOT NULL,
    product_id      INTEGER NOT NULL,
    store_id        INTEGER NOT NULL,
    units_on_hand   INTEGER NOT NULL,
    units_on_order  INTEGER NOT NULL
);

CREATE TABLE retail.fct_web_session (
    session_id      BIGINT PRIMARY KEY,
    customer_id     INTEGER,
    started_ts      TIMESTAMP NOT NULL,
    duration_sec    INTEGER NOT NULL,
    page_views      INTEGER NOT NULL,
    device_type     VARCHAR NOT NULL,
    converted       BOOLEAN NOT NULL
);

CREATE TABLE retail.fct_support_ticket (
    ticket_id       BIGINT PRIMARY KEY,
    customer_id     INTEGER NOT NULL,
    order_id        BIGINT,
    opened_ts       TIMESTAMP NOT NULL,
    closed_ts       TIMESTAMP,
    severity        VARCHAR NOT NULL,
    topic           VARCHAR NOT NULL
);
