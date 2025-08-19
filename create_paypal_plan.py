#!/usr/bin/env python3
"""
Complete PayPal setup script for Givzy Bot
Creates product and billing plan automatically
"""

import requests
import base64
import json
import os
from datetime import datetime

# REPLACE WITH YOUR ACTUAL CREDENTIALS
PAYPAL_CLIENT_ID = "AejrHvx7btvV0nnceh9XnBKEXVFXGhLYvnbz6ZIDfG8fXV83uxK-zG8AQmW82MHTS0RIddOAnmjZSwey"
PAYPAL_CLIENT_SECRET = "EAriDxmoO56lrMN4Icxj61uq7muw6tw5VyZpQNIXLjyzFS4mxPPsQTt9L4j0fdZzrT-9HgXTH9jO-GOs"

# Sandbox URL (change to live for production)
PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"

def get_access_token():
    """Get PayPal access token."""
    url = f"{PAYPAL_BASE_URL}/v1/oauth2/token"
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en_US",
        "Authorization": f"Basic {base64.b64encode(f'{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}'.encode()).decode()}"
    }
    data = "grant_type=client_credentials"
    
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print(f"❌ Auth failed: {response.status_code} - {response.text}")
        return None

def create_product(access_token):
    """Step 1: Create a product (required for billing plan)."""
    url = f"{PAYPAL_BASE_URL}/v1/catalogs/products"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "PayPal-Request-Id": f"PRODUCT-{int(datetime.now().timestamp())}"
    }
    
    product_data = {
        "name": "Givzy Bot Pro Subscription",
        "description": "Monthly subscription for Givzy Discord Bot premium features",
        "type": "SERVICE",
        "category": "SOFTWARE"
    }
    
    response = requests.post(url, headers=headers, json=product_data)
    
    if response.status_code == 201:
        product = response.json()
        print(f"✅ Product created: {product['id']}")
        return product["id"]
    else:
        print(f"❌ Product creation failed: {response.status_code}")
        print(response.text)
        return None

def create_billing_plan(access_token, product_id):
    """Step 2: Create billing plan."""
    url = f"{PAYPAL_BASE_URL}/v1/billing/plans"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "PayPal-Request-Id": f"PLAN-{int(datetime.now().timestamp())}"
    }
    
    plan_data = {
        "product_id": product_id,
        "name": "Givzy Pro Monthly Plan",
        "description": "Monthly subscription for Givzy Bot Pro features - $2.00/month",
        "status": "ACTIVE",
        "billing_cycles": [
            {
                "frequency": {
                    "interval_unit": "MONTH",
                    "interval_count": 1
                },
                "tenure_type": "REGULAR",
                "sequence": 1,
                "total_cycles": 0,  # 0 = infinite
                "pricing_scheme": {
                    "fixed_price": {
                        "value": "2.00",
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "payment_preferences": {
            "auto_bill_outstanding": True,
            "setup_fee": {
                "value": "0.00",
                "currency_code": "USD"
            },
            "setup_fee_failure_action": "CONTINUE",
            "payment_failure_threshold": 3
        },
        "taxes": {
            "percentage": "0.00",
            "inclusive": False
        }
    }
    
    response = requests.post(url, headers=headers, json=plan_data)
    
    if response.status_code == 201:
        plan = response.json()
        print(f"✅ Billing plan created: {plan['id']}")
        return plan["id"]
    else:
        print(f"❌ Plan creation failed: {response.status_code}")
        print(response.text)
        return None

def main():
    print("🚀 Creating PayPal Billing Plan for Givzy Bot")
    print("=" * 50)
    
    # Validate credentials
    if "your_" in PAYPAL_CLIENT_ID or "your_" in PAYPAL_CLIENT_SECRET:
        print("❌ Please update the script with your actual PayPal credentials!")
        print("Get them from: https://developer.paypal.com/dashboard/")
        return
    
    # Get access token
    print("1️⃣ Getting access token...")
    token = get_access_token()
    if not token:
        return
    
    # Create product
    print("2️⃣ Creating product...")
    product_id = create_product(token)
    if not product_id:
        return
    
    # Create billing plan
    print("3️⃣ Creating billing plan...")
    plan_id = create_billing_plan(token, product_id)
    if not plan_id:
        return
    
    # Success!
    print("\n" + "=" * 50)
    print("🎉 SUCCESS! Your PayPal setup is complete!")
    print("=" * 50)
    print(f"📝 Add these to your Render environment variables:")
    print(f"PAYPAL_CLIENT_ID={PAYPAL_CLIENT_ID}")
    print(f"PAYPAL_CLIENT_SECRET={PAYPAL_CLIENT_SECRET}")
    print(f"PAYPAL_PLAN_ID={plan_id}")
    print(f"PAYPAL_PRODUCT_ID={product_id}")

if __name__ == "__main__":
    main()
