from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db

class PriceAndCost(db.Model):
    __tablename__ = 'price_and_cost'
    
    id = Column(Integer, primary_key=True)
    price = Column(Integer, nullable=False)
    rental_price = Column(Integer, nullable=False)
    warranty_period = Column(String(50), nullable=True)
    insurance_status = Column(String(50), nullable=False)
    
    # Foreign key and relationship to Console
    console_id = Column(Integer, ForeignKey('consoles.id'), nullable=False)
    console = relationship('Console', back_populates='price_and_cost')

    def __repr__(self):
        return f"<PriceAndCost price={self.price} rental_price={self.rental_price}>"
