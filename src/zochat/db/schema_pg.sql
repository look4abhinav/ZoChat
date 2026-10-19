-- ZoChat - Postgres schema for the food-delivery support domain.
-- Tables cover customers, restaurants, menu, orders, payments, refunds,
-- deliveries, support tickets and coupons -- the entities a support
-- chatbot agent needs to answer queries about.

-- ---------------------------------------------------------------------------
-- Customers
-- ---------------------------------------------------------------------------
CREATE TABLE customers (
    id              SERIAL PRIMARY KEY,
    name            TEXT    NOT NULL,
    email           TEXT    NOT NULL UNIQUE,
    phone           TEXT    NOT NULL UNIQUE,
    city            TEXT    NOT NULL,
    address         TEXT    NOT NULL,
    loyalty_points  INTEGER NOT NULL DEFAULT 0,
    registered_at   TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- Restaurants
-- ---------------------------------------------------------------------------
CREATE TABLE restaurants (
    id              SERIAL PRIMARY KEY,
    name            TEXT    NOT NULL,
    cuisine         TEXT    NOT NULL,
    city            TEXT    NOT NULL,
    rating          REAL    NOT NULL DEFAULT 0,
    avg_prep_time_min INTEGER NOT NULL DEFAULT 20,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- Menu items offered by a restaurant
-- ---------------------------------------------------------------------------
CREATE TABLE menu_items (
    id              SERIAL PRIMARY KEY,
    restaurant_id   INTEGER NOT NULL,
    name            TEXT    NOT NULL,
    description     TEXT,
    category        TEXT    NOT NULL,
    price           REAL    NOT NULL,
    is_veg          INTEGER NOT NULL DEFAULT 1,
    is_available    INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Delivery partners (riders)
-- ---------------------------------------------------------------------------
CREATE TABLE delivery_partners (
    id              SERIAL PRIMARY KEY,
    name            TEXT    NOT NULL,
    phone           TEXT    NOT NULL UNIQUE,
    vehicle_number  TEXT    NOT NULL,
    city            TEXT    NOT NULL,
    rating          REAL    NOT NULL DEFAULT 5.0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    onboarded_at    TEXT    NOT NULL
);

-- ---------------------------------------------------------------------------
-- Orders
--   status: placed | preparing | picked_up | delivered | cancelled
-- ---------------------------------------------------------------------------
CREATE TABLE orders (
    id                  SERIAL PRIMARY KEY,
    customer_id         INTEGER NOT NULL,
    restaurant_id       INTEGER NOT NULL,
    delivery_partner_id INTEGER,
    status              TEXT    NOT NULL,
    total_amount        REAL    NOT NULL,
    delivery_fee        REAL    NOT NULL DEFAULT 0,
    payment_method      TEXT    NOT NULL,   -- upi | card | wallet | cod
    placed_at           TEXT    NOT NULL,
    delivered_at        TEXT,
    delivery_address    TEXT    NOT NULL,
    rating              INTEGER,
    coupon_code         TEXT,
    cancelled_at        TEXT,
    cancelled_reason    TEXT,
    FOREIGN KEY (customer_id)         REFERENCES customers(id),
    FOREIGN KEY (restaurant_id)       REFERENCES restaurants(id),
    FOREIGN KEY (delivery_partner_id) REFERENCES delivery_partners(id)
);

-- ---------------------------------------------------------------------------
-- Line items within an order
-- ---------------------------------------------------------------------------
CREATE TABLE order_items (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL,
    menu_item_id    INTEGER NOT NULL,
    quantity        INTEGER NOT NULL,
    unit_price      REAL    NOT NULL,
    FOREIGN KEY (order_id)     REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (menu_item_id) REFERENCES menu_items(id)
);

-- ---------------------------------------------------------------------------
-- Payments
--   status: success | failed | pending
-- ---------------------------------------------------------------------------
CREATE TABLE payments (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL,
    method          TEXT    NOT NULL,   -- upi | card | wallet | cod
    amount          REAL    NOT NULL,
    status          TEXT    NOT NULL,
    gateway         TEXT    NOT NULL,   -- razorpay | payu | cashfree | cod
    transaction_id  TEXT    UNIQUE,
    paid_at         TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Refunds
--   status: initiated | approved | processed | rejected
-- ---------------------------------------------------------------------------
CREATE TABLE refunds (
    id              SERIAL PRIMARY KEY,
    payment_id      INTEGER NOT NULL,
    order_id        INTEGER NOT NULL,
    amount          REAL    NOT NULL,
    reason          TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    requested_at    TEXT    NOT NULL,
    processed_at    TEXT,
    FOREIGN KEY (payment_id) REFERENCES payments(id),
    FOREIGN KEY (order_id)   REFERENCES orders(id)
);

-- ---------------------------------------------------------------------------
-- Delivery tracking (separate from orders for live-status modelling)
--   status: assigned | picked_up | in_transit | delivered
-- ---------------------------------------------------------------------------
CREATE TABLE deliveries (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL,
    partner_id      INTEGER NOT NULL,
    status          TEXT    NOT NULL,
    distance_km     REAL,
    picked_up_at    TEXT,
    delivered_at    TEXT,
    FOREIGN KEY (order_id)  REFERENCES orders(id) ON DELETE CASCADE,
    FOREIGN KEY (partner_id) REFERENCES delivery_partners(id)
);

-- ---------------------------------------------------------------------------
-- Support tickets (the unit of work the chatbot agent triages)
--   category: refund | delivery_delay | food_quality | payment | cancellation | other
--   priority: low | medium | high
--   status:   open | in_progress | resolved | closed
-- ---------------------------------------------------------------------------
CREATE TABLE support_tickets (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER NOT NULL,
    order_id        INTEGER,
    category        TEXT    NOT NULL,
    priority        TEXT    NOT NULL DEFAULT 'medium',
    status          TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    resolved_at     TEXT,
    resolution_note TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id),
    FOREIGN KEY (order_id)   REFERENCES orders(id)
);

-- ---------------------------------------------------------------------------
-- Coupons / promotional offers
--   discount_type: percentage | flat
-- ---------------------------------------------------------------------------
CREATE TABLE coupons (
    id              SERIAL PRIMARY KEY,
    code            TEXT    NOT NULL UNIQUE,
    description     TEXT    NOT NULL,
    discount_type   TEXT    NOT NULL,
    discount_value  REAL    NOT NULL,
    max_discount    REAL,
    min_order_value REAL    NOT NULL DEFAULT 0,
    expires_on      TEXT    NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1
);


-- ---------------------------------------------------------------------------
-- Pending actions (two-phase confirmation tokens for mutations)
-- ---------------------------------------------------------------------------
CREATE TABLE pending_actions (
    id              TEXT    PRIMARY KEY,
    customer_id     INTEGER,
    action          TEXT    NOT NULL,
    target_type     TEXT    NOT NULL,
    target_id       INTEGER,
    payload_json    TEXT    NOT NULL,
    created_at      TEXT    NOT NULL,
    expires_at      TEXT    NOT NULL,
    consumed_at     TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- ---------------------------------------------------------------------------
-- Action audit log
-- ---------------------------------------------------------------------------
CREATE TABLE action_audit_log (
    id              SERIAL PRIMARY KEY,
    request_id      TEXT,
    customer_id     INTEGER,
    action          TEXT    NOT NULL,
    target_type     TEXT    NOT NULL,
    target_id       INTEGER,
    status          TEXT    NOT NULL,
    before_json     TEXT,
    after_json      TEXT,
    error_code      TEXT,
    created_at      TEXT    NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

-- ---------------------------------------------------------------------------
-- Coupon redemptions
-- ---------------------------------------------------------------------------
CREATE TABLE coupon_redemptions (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL UNIQUE,
    coupon_code     TEXT    NOT NULL,
    discount_amount REAL    NOT NULL,
    original_total  REAL    NOT NULL,
    final_total     REAL    NOT NULL,
    applied_at      TEXT    NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- Helpful indexes for the chatbot's common lookups
-- ---------------------------------------------------------------------------
CREATE INDEX idx_orders_customer        ON orders(customer_id);
CREATE INDEX idx_orders_status          ON orders(status);
CREATE INDEX idx_order_items_order      ON order_items(order_id);
CREATE INDEX idx_payments_order         ON payments(order_id);
CREATE INDEX idx_refunds_order          ON refunds(order_id);
CREATE INDEX idx_deliveries_order       ON deliveries(order_id);
CREATE INDEX idx_tickets_customer       ON support_tickets(customer_id);
CREATE INDEX idx_tickets_status         ON support_tickets(status);
CREATE INDEX idx_menu_items_restaurant  ON menu_items(restaurant_id);
CREATE INDEX idx_pending_actions_customer ON pending_actions(customer_id);
CREATE INDEX idx_audit_request          ON action_audit_log(request_id);
CREATE INDEX idx_audit_customer         ON action_audit_log(customer_id);
