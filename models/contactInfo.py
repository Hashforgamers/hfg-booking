from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from db.extensions import db


class ContactInfo(db.Model):
    __tablename__ = 'contact_info'
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=False)
    
    # Generic parent relationship columns
    parent_id = Column(Integer, nullable=False)
    parent_type = Column(String(50), nullable=False)
