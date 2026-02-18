from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db

class AdditionalDetails(db.Model):
    __tablename__ = 'additional_details'
    
    id = Column(Integer, primary_key=True)
    supported_games = Column(String(500), nullable=True)
    accessories = Column(String(500), nullable=True)
    
    # Foreign key and relationship to Console
    console_id = Column(Integer, ForeignKey('consoles.id'), nullable=False)
    console = relationship('Console', back_populates='additional_details')

    def __repr__(self):
        return f"<AdditionalDetails supported_games={self.supported_games}>"
