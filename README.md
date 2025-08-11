# HFG Booking Service

## Overview
The HFG Booking Service is a Flask-based backend service that handles booking operations for gaming slots. It provides:
- Slot availability management
- Real-time booking updates via WebSocket
- Integration with user wallets and payment systems
- Vendor-specific dashboards and reporting

## Key Features
- **Slot Booking**: Reserve gaming slots with real-time availability checks
- **Booking Management**: View, modify, and cancel bookings
- **Payment Integration**: Supports wallet payments and external payment gateways
- **Real-time Updates**: WebSocket events for booking status changes
- **Vendor Dashboards**: Automatic updates to vendor-specific dashboard tables
- **Promo Code Handling**: Supports promotional discounts and tracking

## Models

### Booking (`models/booking.py`)
Core booking entity with relationships to:
- AvailableGames (through `game_id`)
- Slots (through `slot_id`)
- Transactions (1:1 relationship)
- AccessBookingCodes (optional for promo/access codes)

```json
{
  "booking_id": 123,
  "user_id": 456,
  "status": "pending_verified",
  "slot": {
    "id": 789,
    "start_time": "19:00",
    "end_time": "20:00"
  },
  "access_code": "ABC123",
  "book_date": "2025-01-01"
}
```

## Core Services

### BookingService (`services/booking_service.py`)

Main operations:
- `create_booking()`: Create a new booking with slot availability checks
- `cancel_booking()`: Cancel existing booking and free up slot
- `release_slot()`: Automated slot release for timed-out verifications
- `verifyPayment()`: Payment verification handler
- `get_user_bookings()`: Retrieve all bookings for a user

**Real-time Events:**
- `booking_updated`: Emitted when booking status changes
- `slot_pending`: Emitted when slot is temporarily reserved
- `slot_released`: Emitted when slot becomes available

## Vendor Integration
The service automatically updates vendor-specific tables:

### Vendor Dashboard Tables
Format: `VENDOR_{vendor_id}_DASHBOARD`  
Contains:
- Booking details
- Slot timing
- User information
- Current status

### Vendor Promo Tables
Format: `VENDOR_{vendor_id}_PROMO_DETAIL`  
Tracks:
- Promo codes used
- Discounts applied
- Transaction amounts

## Setup

1. **Prerequisites**:
   - Python 3.10+
   - PostgreSQL
   - Redis (for WebSocket support)

2. **Installation**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Configuration**:
   Configure environment variables in `.env`:
   ```
   DATABASE_URL=postgresql://user:password@localhost/hfg_booking
   REDIS_URL=redis://localhost:6379/0
   ```

4. **Database Setup**:
   ```bash
   flask db upgrade
   ```

5. **Run the Service**:
   ```bash
   flask run
   ```

## API Endpoints

### Booking Controller

#### POST /create_order
Creates a Razorpay payment order

**Request:**
```json
{
  "amount": 50000,
  "currency": "INR",
  "receipt": "order_rcpt_123"
}
```

**Response (Success):**
```json
{
  "id": "order_ABC123",
  "amount": 50000,
  "currency": "INR",
  "status": "created"
}
```

#### POST /bookings
Creates booking and freezes slots

**Request:**
```json
{
  "slot_id": [101, 102],
  "user_id": 456,
  "game_id": 789,
  "book_date": "2025-08-15"
}
```

**Response (Success):**
```json
{
  "message": "Slots frozen",
  "bookings": [
    {"slot_id": 101, "booking_id": 123},
    {"slot_id": 102, "booking_id": 124}
  ]
}
```

#### GET /bookings/<booking_id>
Get booking details

**Response (Success):**
```json
{
  "booking": {
    "booking_id": "BK-123",
    "date": "2025-08-15",
    "time_slot": {
      "start_time": "19:00",
      "end_time": "20:00"
    },
    "system": "PS5",
    "customer": {
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+919876543210"
    },
    "amount_paid": 500
  }
}
```

[Other endpoints remain listed as before...]

### Game Controller

#### GET /games
Get all available games

**Response (Success):**
```json
[
  {
    "id": 789,
    "game_name": "FIFA 25",
    "total_slots": 4,
    "single_slot_price": 500
  },
  {
    "id": 790,
    "game_name": "Call of Duty",
    "total_slots": 2,
    "single_slot_price": 600
  }
]
```

#### GET /games/vendor/<int:vendor_id>
Get games available at vendor

**Response (Success):**
```json
{
  "games": [
    {
      "id": 789,
      "game_name": "FIFA 25",
      "total_slots": 4,
      "single_slot_price": 500,
      "opening_days": ["mon", "tue", "wed", "thu", "fri"]
    }
  ],
  "shop_open": true,
  "game_count": 1
}
```

#### POST /bookings
Create new booking

**Request:**
```json
{
  "user_id": 456,
  "game_id": 789,
  "slot_id": [101],
  "book_date": "2025-08-15"
}
```

**Response (Success, 201 Created):**
```json
{
  "id": 123,
  "user_id": 456,
  "game_id": 789
}
```

#### GET /bookings/user/<int:user_id>
Get user's bookings

**Response (Success):**
```json
[
  {
    "booking_id": 123,
    "user_id": 456,
    "game_id": 789,
    "status": "confirmed",
    "book_date": "2025-08-15"
  }
]
```

#### DELETE /bookings/<int:booking_id>
Cancel booking

**Response (Success):**
```json
{
  "message": "Booking canceled successfully"
}
```

#### GET /getAllConsole/vendor/<int:vendor_id>
Get all consoles by vendor

**Response (Success):**
```json
{
  "consoles": [
    {
      "id": 1,
      "model_number": "PS5",
      "status": "available"
    },
    {
      "id": 2,
      "model_number": "Xbox Series X",
      "status": "in_use"
    }
  ]
}
```

### Gaming Type Controller

#### GET /gaming-types
Get all gaming types

**Response (Success):**
```json
[
  {
    "id": 1,
    "name": "Console Gaming",
    "description": "Playstation/Xbox gaming stations"
  },
  {
    "id": 2,
    "name": "PC Gaming",
    "description": "High-end gaming PCs"
  }
]
```

#### POST /gaming-types
Create new gaming type

**Request:**
```json
{
  "name": "VR Gaming",
  "description": "Virtual Reality gaming setup"
}
```

**Response (Success, 201 Created):**
```json
{
  "id": 3,
  "name": "VR Gaming",
  "description": "Virtual Reality gaming setup"
}
```

#### DELETE /gaming-types/<int:gaming_type_id>
Delete gaming type

**Response (Success):**
```json
{
  "message": "Gaming type deleted"
}
```

### Slot Controller

#### GET /slots
Get all slot definitions

**Response (Success):**
```json
[
  {
    "id": 101,
    "start_time": "10:00:00",
    "end_time": "11:00:00",
    "gaming_type_id": 1
  },
  {
    "id": 102,
    "start_time": "11:00:00",
    "end_time": "12:00:00",
    "gaming_type_id": 1
  }
]
```

#### GET /getSlots/vendor/<int:vendorId>/game/<int:gameId>/<string:date>
Get available slots for specific vendor/game/date

**Parameters:**
- vendorId: Vendor ID (e.g. 123)
- gameId: Game ID (e.g. 456)
- date: Date in YYYYMMDD format (e.g. "20250815")

**Response (Success):**
```json
{
  "slots": [
    {
      "slot_id": 101,
      "start_time": "10:00:00",
      "end_time": "11:00:00",
      "is_available": true,
      "available_slot": 2,
      "single_slot_price": 500
    }
  ]
}
```

#### GET /getSlotList/vendor/<int:vendor_id>/game/<int:game_id>
Get next 6 available slots for game

**Response (Success):**
```json
[
  {
    "slot_id": 101,
    "start_time": "14:00:00",
    "end_time": "15:00:00",
    "is_available": true
  },
  {
    "slot_id": 102,
    "start_time": "15:00:00",
    "end_time": "16:00:00",
    "is_available": true
  }
]
```

## WebSocket Events
Connect to `/socket.io`:
- **Subscriptions**:
  - `subscribe_bookings` - Receive updates for a user's bookings
  - `subscribe_slots` - Receive slot availability updates