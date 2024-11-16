from models.gaming_type import GamingType, db

class GamingTypeService:
    @staticmethod
    def get_all_gaming_types():
        """
        Fetch all available gaming types.
        """
        return GamingType.query.all()

    @staticmethod
    def create_gaming_type(data):
        """
        Create a new gaming type.
        :param data: Dictionary containing 'name'
        """
        if 'name' not in data or not data['name']:
            raise ValueError("Gaming type name is required.")

        gaming_type = GamingType(name=data['name'])
        db.session.add(gaming_type)
        db.session.commit()
        return gaming_type

    @staticmethod
    def delete_gaming_type(gaming_type_id):
        """
        Delete an existing gaming type.
        :param gaming_type_id: ID of the gaming type to be deleted
        """
        gaming_type = GamingType.query.get(gaming_type_id)
        if not gaming_type:
            return False

        db.session.delete(gaming_type)
        db.session.commit()
        return True
