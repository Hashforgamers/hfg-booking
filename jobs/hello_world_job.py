"""
Hello World Job Script for Render One-Off Job
Runs in a loop every 30 seconds for 30 days.
"""

import logging
from datetime import datetime, timedelta
import sys
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def run_job():
    """
    Executes one iteration of the Hello World job
    """
    try:
        print("=" * 50)
        print("🎮 HFG BOOKING SERVICE - HELLO WORLD JOB")
        print("=" * 50)
        
        # Get current timestamp
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Log and print messages
        message = "Hello World from HFG Booking Service!"
        print(f"📢 {message}")
        print(f"⏰ Job executed at: {current_time}")
        print(f"🐍 Python version: {sys.version}")
        
        # Log the execution
        logging.info(message)
        logging.info(f"Job executed successfully at: {current_time}")
        
        print("=" * 50)
        print("✅ Job completed successfully!")
        print("=" * 50)
        
        return True
        
    except Exception as e:
        error_msg = f"❌ Job failed with error: {str(e)}"
        print(error_msg)
        logging.error(error_msg)
        return False


def main():
    # Define duration
    duration_days = 30
    end_time = datetime.now() + timedelta(days=duration_days)
    
    logging.info(f"Starting loop for {duration_days} days.")
    
    while datetime.now() < end_time:
        success = run_job()
        if not success:
            logging.error("Job iteration failed. Continuing to next iteration...")
        
        # Sleep 30 seconds before next run
        time.sleep(30)
    
    logging.info("Loop finished after 30 days.")


if __name__ == "__main__":
    main()
