from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db

class MaintenanceStatus(db.Model):
    __tablename__ = 'maintenance_status'
    
    id = Column(Integer, primary_key=True)
    available_status = Column(String(50), nullable=False)
    condition = Column(String(50), nullable=False)
    last_maintenance = Column(Date, nullable=False)
    next_maintenance = Column(Date, nullable=False)
    maintenance_notes = Column(String(500), nullable=True)
    
    # Foreign key and relationship to Console
    console_id = Column(Integer, ForeignKey('consoles.id'), nullable=False)
    console = relationship('Console', back_populates='maintenance_status')

    def __repr__(self):
        return f"<MaintenanceStatus available_status={self.available_status} condition={self.condition}>"
