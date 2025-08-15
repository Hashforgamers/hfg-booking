from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from db.extensions import db
from datetime import datetime

class ExtraServiceMenuImage(db.Model):
    __tablename__ = 'extra_service_menu_images'
    
    id = Column(Integer, primary_key=True)
    menu_id = Column(Integer, ForeignKey('extra_service_menus.id'), nullable=False)
    image_url = Column(String(500), nullable=False)  # Cloudinary URL
    public_id = Column(String(255), nullable=False)   # Cloudinary public_id
    alt_text = Column(String(255), nullable=True)
    is_primary = Column(Boolean, default=False)       # Mark primary image
    is_active = Column(Boolean, default=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    menu_item = relationship('ExtraServiceMenu', back_populates='images')
    
    def __str__(self):
        return f"<ExtraServiceMenuImage {self.id} for Menu {self.menu_id}>"
