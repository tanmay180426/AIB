"""SQLAlchemy models for the analytical warehouse (star schema).

Grain:
- fact_order_items: one row per order line (order_id + order_item_id)
- fact_orders: one row per order (order-level measures, including the
  primary payment method: the highest-value payment of the order)
- dimensions: customer, product, seller, date

All monetary values are in the dataset's original currency (BRL). No profit,
margin, or inventory measures are derived because the dataset does not support them.
"""

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    Boolean,
    ForeignKey,
)

from app.database.session import Base


class DimCustomer(Base):
    __tablename__ = "dim_customer"

    customer_unique_id = Column(String, primary_key=True)
    customer_zip_code_prefix = Column(String, nullable=True)
    customer_city = Column(String, nullable=True)
    customer_state = Column(String, nullable=True)


class DimProduct(Base):
    __tablename__ = "dim_product"

    product_id = Column(String, primary_key=True)
    product_category_name_pt = Column(String, nullable=True)
    product_category_name_en = Column(String, nullable=True)
    product_weight_g = Column(Float, nullable=True)


class DimSeller(Base):
    __tablename__ = "dim_seller"

    seller_id = Column(String, primary_key=True)
    seller_zip_code_prefix = Column(String, nullable=True)
    seller_city = Column(String, nullable=True)
    seller_state = Column(String, nullable=True)


class DimDate(Base):
    __tablename__ = "dim_date"

    date_key = Column(Date, primary_key=True)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    day = Column(Integer, nullable=False)
    quarter = Column(Integer, nullable=False)
    weekday = Column(Integer, nullable=False)


class FactOrders(Base):
    __tablename__ = "fact_orders"

    order_id = Column(String, primary_key=True)
    customer_unique_id = Column(String, ForeignKey("dim_customer.customer_unique_id"), nullable=True)
    order_status = Column(String, nullable=True)
    purchase_date = Column(Date, nullable=True)
    delivered_customer_date = Column(Date, nullable=True)
    estimated_delivery_date = Column(Date, nullable=True)
    delivery_days = Column(Float, nullable=True)
    is_late = Column(Boolean, nullable=True)
    review_score = Column(Float, nullable=True)
    payment_value = Column(Float, nullable=True)
    payment_type = Column(String, nullable=True)
    payment_installments = Column(Integer, nullable=True)
    item_revenue = Column(Float, nullable=True)
    freight_value = Column(Float, nullable=True)


class FactOrderItems(Base):
    __tablename__ = "fact_order_items"

    row_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String, ForeignKey("fact_orders.order_id"), nullable=False)
    order_item_id = Column(Integer, nullable=False)
    product_id = Column(String, ForeignKey("dim_product.product_id"), nullable=True)
    seller_id = Column(String, ForeignKey("dim_seller.seller_id"), nullable=True)
    customer_unique_id = Column(String, nullable=True)
    purchase_date = Column(Date, nullable=True)
    price = Column(Float, nullable=False)
    freight_value = Column(Float, nullable=False)
    product_category_name_en = Column(String, nullable=True)
