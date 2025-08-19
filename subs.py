import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import requests
import base64
import secrets

# PayPal API configuration
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
PAYPAL_BASE_URL = "https://api-m.sandbox.paypal.com"  # Use https://api-m.paypal.com for production

# Subscription database channel ID
SUBSCRIPTION_DB_CHANNEL_ID = 1406622696326041641

# Global subscription data
subscriptions = {}

class SubscriptionTier:
    FREE = "free"
    PRO = "pro"

def get_paypal_access_token():
    """Get PayPal access token for API calls."""
    if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
        logging.error("PayPal credentials not configured")
        return None
    
    try:
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
            logging.error(f"PayPal auth failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logging.error(f"Error getting PayPal token: {e}")
        return None

def create_paypal_subscription(server_id: str, server_name: str):
    """Create a PayPal subscription for a server."""
    access_token = get_paypal_access_token()
    if not access_token:
        return None
    
    try:
        # Create subscription
        url = f"{PAYPAL_BASE_URL}/v1/billing/subscriptions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "PayPal-Request-Id": f"givzy-sub-{server_id}-{secrets.token_hex(8)}"
        }
        
        # Generate a unique plan ID or use a pre-created one
        plan_id = "P-0WW54101YC976010WNCR7M4Y"  # Your actual PayPal plan ID
        
        subscription_data = {
            "plan_id": plan_id,
            "custom_id": f"givzy-{server_id}",
            "application_context": {
                "brand_name": "Givzy Bot",
                "locale": "en-US",
                "shipping_preference": "NO_SHIPPING",
                "user_action": "SUBSCRIBE_NOW",
                "payment_method": {
                    "payer_selected": "PAYPAL",
                    "payee_preferred": "IMMEDIATE_PAYMENT_REQUIRED"
                },
                "return_url": "https://example.com/return",  # Replace with your return URL
                "cancel_url": "https://example.com/cancel"   # Replace with your cancel URL
            }
        }
        
        response = requests.post(url, headers=headers, json=subscription_data)
        
        if response.status_code == 201:
            subscription = response.json()
            approval_url = None
            
            for link in subscription.get("links", []):
                if link.get("rel") == "approve":
                    approval_url = link.get("href")
                    break
            
            return {
                "subscription_id": subscription.get("id"),
                "approval_url": approval_url
            }
        else:
            logging.error(f"PayPal subscription creation failed: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logging.error(f"Error creating PayPal subscription: {e}")
        return None

def is_server_subscribed(server_id: int) -> bool:
    """Check if a server has an active Pro subscription."""
    server_data = subscriptions.get(str(server_id))
    if not server_data:
        return False
    
    if server_data.get("tier") != SubscriptionTier.PRO:
        return False
    
    # Check if subscription is still active
    expires_at = server_data.get("expires_at")
    if expires_at:
        try:
            expiry_date = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            return datetime.now(timezone.utc) < expiry_date
        except (ValueError, AttributeError):
            return False
    
    return False

def get_server_tier(server_id: int) -> str:
    """Get the subscription tier for a server."""
    if is_server_subscribed(server_id):
        return SubscriptionTier.PRO
    return SubscriptionTier.FREE

async def load_subscriptions(bot):
    """Load subscription data from the database channel."""
    global subscriptions
    
    try:
        db_channel = bot.get_channel(SUBSCRIPTION_DB_CHANNEL_ID)
        if not db_channel:
            logging.error(f"Subscription database channel {SUBSCRIPTION_DB_CHANNEL_ID} not found!")
            subscriptions = {}
            return

        subscriptions = {}
        
        # Look for the most recent valid subscription database message
        async for message in db_channel.history(limit=20):
            if message.author == bot.user and message.content.startswith("```json"):
                try:
                    json_content = message.content[7:-3].strip()  # Remove ```json and ```
                    if json_content:
                        data = json.loads(json_content)
                        if isinstance(data, dict) and "subscriptions" in data:
                            subscriptions = data["subscriptions"]
                            logging.info(f"✅ Loaded {len(subscriptions)} subscription records")
                            return
                except json.JSONDecodeError:
                    continue
        
        # If no valid data found, start with empty subscriptions
        logging.info("📝 No subscription data found, starting with empty database")
        subscriptions = {}
        
    except Exception as e:
        logging.error(f"Critical error loading subscriptions: {e}")
        subscriptions = {}

async def save_subscriptions(bot):
    """Save subscription data to the database channel."""
    try:
        db_channel = bot.get_channel(SUBSCRIPTION_DB_CHANNEL_ID)
        if not db_channel:
            logging.error(f"Subscription database channel {SUBSCRIPTION_DB_CHANNEL_ID} not found!")
            return

        # Create subscription database structure
        subscription_data = {
            "subscriptions": subscriptions,
            "metadata": {
                "version": "1.0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "total_subscriptions": len(subscriptions),
                "active_subscriptions": sum(1 for s in subscriptions.values() if s.get("tier") == SubscriptionTier.PRO)
            }
        }
        
        json_content = json.dumps(subscription_data, indent=2, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        
        message_content = f"```json\n{json_content}\n```"
        
        embed = discord.Embed(
            title="💳 Givzy Subscription Database",
            description=f"**Total Subscriptions:** {len(subscriptions)}\n"
                       f"**Active Pro:** {subscription_data['metadata']['active_subscriptions']}\n"
                       f"**Last Updated:** {timestamp}",
            color=discord.Color.gold(),
            timestamp=datetime.now(timezone.utc)
        )
        
        await db_channel.send(content=message_content, embed=embed)
        logging.info(f"✅ Subscription database saved successfully")
        
    except Exception as e:
        logging.error(f"Critical error saving subscriptions: {e}")

def add_subscription_commands(tree: app_commands.CommandTree, bot):
    """Add subscription-related commands to the command tree."""
    
    @tree.command(name="buy", description="Subscribe to Givzy Pro ($2/month)")
    async def buy_subscription(interaction: discord.Interaction):
    @tree.command(name="buy", description="Subscribe to Givzy Pro ($2/month)")
    async def buy_subscription(interaction: discord.Interaction):
        """Handle Pro subscription purchase."""
        # Only server owners can subscribe
        if interaction.user.id != interaction.guild.owner_id:
            await interaction.response.send_message(
                "❌ Only the server owner can purchase subscriptions for this server.",
                ephemeral=True
            )
            return
        
        # Check if PayPal is configured
        if not PAYPAL_CLIENT_ID or not PAYPAL_CLIENT_SECRET:
            await interaction.response.send_message(
                "💳 **Givzy Pro Subscription**\n\n"
                "**✨ Pro Features Include:**\n"
                "• 🛡️ Role requirements for giveaways\n"
                "• ⏰ Minimum account age restrictions\n"
                "• 🏠 Minimum server time requirements\n"
                "• 🔒 Enhanced security and moderation\n\n"
                "**💰 Price:** $2.00/month\n\n"
                "⚠️ **Payment system is currently being set up.**\n"
                "Please contact the bot administrator to upgrade to Pro tier.\n\n"
                "🎉 All free features are available and working perfectly!",
                ephemeral=True
            )
            return
        
        # Check if already subscribed
        if is_server_subscribed(interaction.guild.id):
            server_data = subscriptions.get(str(interaction.guild.id))
            expires_at = server_data.get("expires_at", "Unknown")
            
            try:
                timestamp = int(datetime.fromisoformat(expires_at.replace('Z', '+00:00')).timestamp())
                await interaction.response.send_message(
                    f"✅ This server already has Givzy Pro!\n"
                    f"**Expires:** <t:{timestamp}:F>",
                    ephemeral=True
                )
            except:
                await interaction.response.send_message(
                    "✅ This server already has Givzy Pro!\n"
                    f"**Expires:** {expires_at}",
                    ephemeral=True
                )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        # Create PayPal subscription
        paypal_data = create_paypal_subscription(str(interaction.guild.id), interaction.guild.name)
        
        if not paypal_data or not paypal_data.get("approval_url"):
            await interaction.followup.send(
                "❌ **Payment System Temporarily Unavailable**\n\n"
                "We're experiencing issues with our payment processor.\n"
                "Please try again later or contact support.\n\n"
                "🎉 All free features are available and working perfectly!",
                ephemeral=True
            )
            return
        
        # Store pending subscription
        subscriptions[str(interaction.guild.id)] = {
            "server_name": interaction.guild.name,
            "tier": SubscriptionTier.FREE,  # Will be upgraded after payment
            "status": "pending",
            "paypal_subscription_id": paypal_data["subscription_id"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "owner_id": interaction.user.id
        }
        
        await save_subscriptions(bot)
        
        embed = discord.Embed(
            title="💳 Subscribe to Givzy Pro",
            description=(
                "**🎉 Unlock Premium Features!**\n\n"
                "**Pro Features Include:**\n"
                "• 🛡️ Role requirements for giveaways\n"
                "• ⏰ Minimum account age restrictions\n"
                "• 🏠 Minimum server time requirements\n"
                "• 🔒 Enhanced security and moderation\n\n"
                "**💰 Price:** $2.00/month\n"
                "**🔄 Billing:** Automatically renews monthly\n"
                "**⏰ Access:** Instant activation after payment\n\n"
                "Click the button below to complete your subscription!"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Secure payment processed by PayPal")
        
        # Create a view with the PayPal payment button
        view = discord.ui.View()
        pay_button = discord.ui.Button(
            label="💳 Pay with PayPal ($2/month)",
            style=discord.ButtonStyle.url,
            url=paypal_data["approval_url"]
        )
        view.add_item(pay_button)
        
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    
    @tree.command(name="subscription", description="Check your server's subscription status")
    async def check_subscription(interaction: discord.Interaction):
        """Check the current subscription status of the server."""
        server_id = str(interaction.guild.id)
        server_data = subscriptions.get(server_id)
        
        if not server_data or server_data.get("tier") == SubscriptionTier.FREE:
            embed = discord.Embed(
                title="📋 Subscription Status - Free Tier",
                description=(
                    "**Current Plan:** Free\n"
                    "**Status:** Active\n\n"
                    "**Available Features:**\n"
                    "• ✅ Basic giveaway creation\n"
                    "• ✅ Winner selection and rerolls\n"
                    "• ✅ Giveaway management\n\n"
                    "**🚀 Upgrade to Pro for:**\n"
                    "• 🛡️ Role requirements\n"
                    "• ⏰ Account age restrictions\n"
                    "• 🏠 Server time requirements\n\n"
                    "Use `/buy` to upgrade to Pro for just $2/month!"
                ),
                color=discord.Color.blue()
            )
        else:
            # Pro subscription
            expires_at = server_data.get("expires_at")
            status = "Active" if is_server_subscribed(interaction.guild.id) else "Expired"
            
            embed = discord.Embed(
                title="✨ Subscription Status - Pro Tier",
                description=(
                    f"**Current Plan:** Pro\n"
                    f"**Status:** {status}\n"
                    f"**Expires:** <t:{int(datetime.fromisoformat(expires_at.replace('Z', '+00:00')).timestamp())}:F>\n\n"
                    "**Pro Features Unlocked:**\n"
                    "• ✅ All Free features\n"
                    "• ✅ Role requirements for giveaways\n"
                    "• ✅ Minimum account age restrictions\n"
                    "• ✅ Minimum server time requirements\n"
                    "• ✅ Enhanced security and moderation\n\n"
                    "Thank you for supporting Givzy! 🎉"
                ),
                color=discord.Color.gold()
            )
            
            if status == "Expired":
                embed.add_field(
                    name="⚠️ Subscription Expired",
                    value="Use `/buy` to renew your Pro subscription and restore access to premium features.",
                    inline=False
                )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Webhook handler for PayPal (you'll need to implement this in your web server)
def handle_paypal_webhook(webhook_data):
    """Handle PayPal webhook notifications for subscription events."""
    try:
        event_type = webhook_data.get("event_type")
        resource = webhook_data.get("resource", {})
        
        if event_type == "BILLING.SUBSCRIPTION.ACTIVATED":
            # Subscription activated
            custom_id = resource.get("custom_id", "")
            if custom_id.startswith("givzy-"):
                server_id = custom_id.replace("givzy-", "")
                
                # Activate subscription
                if server_id in subscriptions:
                    subscriptions[server_id]["tier"] = SubscriptionTier.PRO
                    subscriptions[server_id]["status"] = "active"
                    subscriptions[server_id]["activated_at"] = datetime.now(timezone.utc).isoformat()
                    subscriptions[server_id]["expires_at"] = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
                    
                    logging.info(f"✅ Subscription activated for server {server_id}")
        
        elif event_type == "BILLING.SUBSCRIPTION.CANCELLED":
            # Subscription cancelled
            custom_id = resource.get("custom_id", "")
            if custom_id.startswith("givzy-"):
                server_id = custom_id.replace("givzy-", "")
                
                if server_id in subscriptions:
                    subscriptions[server_id]["status"] = "cancelled"
                    subscriptions[server_id]["cancelled_at"] = datetime.now(timezone.utc).isoformat()
                    
                    logging.info(f"❌ Subscription cancelled for server {server_id}")
        
    except Exception as e:
        logging.error(f"Error processing PayPal webhook: {e}")

def check_feature_access(server_id: int, feature: str) -> tuple[bool, str]:
    """
    Check if a server has access to a specific feature.
    
    Args:
        server_id: The Discord server ID
        feature: The feature to check ('role_requirement', 'account_age', 'server_time')
    
    Returns:
        tuple: (has_access: bool, error_message: str)
    """
    tier = get_server_tier(server_id)
    
    pro_features = ['role_requirement', 'account_age', 'server_time']
    
    if feature in pro_features and tier == SubscriptionTier.FREE:
        return False, f"❌ **{feature.replace('_', ' ').title()}** is a Pro feature. Use `/buy` to upgrade for $2/month!"
    
    return True, ""
