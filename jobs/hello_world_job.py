
"""
Hello World Job Script for Render One-Off Job
This is the actual job that Render will execute.
"""

import logging
from datetime import datetime
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    """
    Main function that executes the Hello World job
    """
    try:
        # Print Hello World message
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

if __name__ == "__main__":
    success = main()
    # Exit with appropriate code
    sys.exit(0 if success else 1)
