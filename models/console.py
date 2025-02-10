from sqlalchemy import Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import relationship
from db.extensions import db
from models.availableGame import available_game_console 

class Console(db.Model):
    __tablename__ = 'consoles'
    
    id = Column(Integer, primary_key=True)
    console_number = Column(Integer, nullable=False)
    model_number = Column(String(50), nullable=False)
    serial_number = Column(String(100), nullable=False)
    brand = Column(String(50), nullable=False)
    console_type = Column(String(50), nullable=False)
    release_date = Column(Date, nullable=False)
    description = Column(String(500), nullable=True)


    def __repr__(self):
        return f"<Console console_type={self.console_type} model_number={self.model_number}>"
