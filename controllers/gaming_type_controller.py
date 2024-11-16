from flask import Blueprint, request, jsonify
from services.gaming_type_service import GamingTypeService

gaming_type_blueprint = Blueprint('gaming_types', __name__)

@gaming_type_blueprint.route('/gaming-types', methods=['GET'])
def get_gaming_types():
    gaming_types = GamingTypeService.get_all_gaming_types()
    return jsonify([gt.to_dict() for gt in gaming_types])

@gaming_type_blueprint.route('/gaming-types', methods=['POST'])
def create_gaming_type():
    data = request.json
    gaming_type = GamingTypeService.create_gaming_type(data)
    return jsonify(gaming_type.to_dict()), 201

@gaming_type_blueprint.route('/gaming-types/<int:gaming_type_id>', methods=['DELETE'])
def delete_gaming_type(gaming_type_id):
    success = GamingTypeService.delete_gaming_type(gaming_type_id)
    if not success:
        return jsonify({"message": "Gaming type not found"}), 404
    return jsonify({"message": "Gaming type deleted"})
