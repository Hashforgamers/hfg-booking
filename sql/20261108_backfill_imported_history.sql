-- Run after 20261103_desk_rates_and_history.sql and 20261103_imported_transactions.sql.
-- Posts existing imported history to Transaction Report; does not create live bookings or slots.
BEGIN;
        INSERT INTO transactions (vendor_id,reference_id,user_name,booked_date,booking_date,booking_time,
            amount,original_amount,discounted_amount,mode_of_payment,payment_use_case,booking_type,
            settlement_status,source_channel,base_amount,meals_amount,controller_amount,waive_off_amount,
            app_fee_amount,taxable_amount,gst_rate,cgst_amount,sgst_amount,igst_amount,total_with_tax,created_at,updated_at)
        SELECT vendor_id,source_key,player,played_on,played_on + (ended < started)::integer,ended,
            paid,paid,0,'Unspecified','historical_payment','historical_session','completed','excel_import',
            paid,0,0,0,0,0,0,0,0,0,paid,now(),now()
        FROM desk_booking_archive WHERE TRUE
        ON CONFLICT (vendor_id,reference_id) WHERE source_channel='excel_import' DO UPDATE
        SET user_name=excluded.user_name,booked_date=excluded.booked_date,booking_date=excluded.booking_date,
            booking_time=excluded.booking_time,amount=excluded.amount,original_amount=excluded.amount,
            base_amount=excluded.amount,total_with_tax=excluded.amount,updated_at=now()
        WHERE (transactions.user_name,transactions.booked_date,transactions.booking_date,transactions.booking_time,transactions.amount)
              IS DISTINCT FROM (excluded.user_name,excluded.booked_date,excluded.booking_date,excluded.booking_time,excluded.amount)
;
COMMIT;
