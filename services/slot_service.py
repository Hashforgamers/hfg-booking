from models.slot import Slot, db

class SlotService:
    @staticmethod
    def get_all_slots():
        return Slot.query.all()

    @staticmethod
    def create_slot(data):
        slot = Slot(**data)
        db.session.add(slot)
        db.session.commit()
        return slot

    @staticmethod
    def update_slot(slot_id, data):
        slot = Slot.query.get(slot_id)
        if not slot:
            return None
        for key, value in data.items():
            setattr(slot, key, value)
        db.session.commit()
        return slot

    @staticmethod
    def delete_slot(slot_id):
        slot = Slot.query.get(slot_id)
        if slot:
            db.session.delete(slot)
            db.session.commit()
            return True
        return False
