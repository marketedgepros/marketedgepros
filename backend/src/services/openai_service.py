"""
OpenAI GPT-5 Service
Handles all interactions with OpenAI API
"""
import os
from openai import OpenAI

class OpenAIService:
    """Service for OpenAI GPT-5 integration"""
    
    def __init__(self):
        """Initialize OpenAI client"""
        api_key = os.getenv('OPENAI_API_KEY')
        api_base = os.getenv('OPENAI_API_BASE')
        
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        
        # Initialize OpenAI client
        if api_base:
            self.client = OpenAI(api_key=api_key, base_url=api_base)
        else:
            self.client = OpenAI(api_key=api_key)
    
    def chat_completion(self, messages, model="gpt-5", temperature=0.7, max_tokens=1000):
        """
        Generate chat completion using GPT-5
        
        Args:
            messages (list): List of message dictionaries with 'role' and 'content'
            model (str): Model to use (default: gpt-5)
            temperature (float): Sampling temperature (0-2)
            max_tokens (int): Maximum tokens to generate
            
        Returns:
            dict: Response containing message and usage info
        """
        try:
            response = self.client.responses.create(
                model=model,
                input=messages[-1]['content'] if messages else "",
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return {
                'success': True,
                'message': response.output,
                'usage': {
                    'prompt_tokens': getattr(response, 'prompt_tokens', 0),
                    'completion_tokens': getattr(response, 'completion_tokens', 0),
                    'total_tokens': getattr(response, 'total_tokens', 0)
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_trading_advice(self, user_query, user_context=None):
        """
        Get trading advice from GPT-5
        
        Args:
            user_query (str): User's question
            user_context (dict): Optional user context (role, challenges, etc.)
            
        Returns:
            dict: Response with advice
        """
        system_message = """You are a professional trading advisor for MarketEdgePros, 
a prop trading firm. You help traders with:
- Understanding trading programs and challenges
- Risk management strategies
- Trading psychology and discipline
- Platform features and rules
- General trading education

Always be professional, supportive, and educational. 
Do not provide specific trade recommendations or financial advice.
Focus on education and helping traders succeed in their evaluation."""

        messages = [
            {"role": "system", "content": system_message}
        ]
        
        # Add user context if provided
        if user_context:
            context_str = f"User context: {user_context.get('role', 'trader')}"
            if user_context.get('challenges'):
                context_str += f", Active challenges: {len(user_context['challenges'])}"
            messages.append({"role": "system", "content": context_str})
        
        messages.append({"role": "user", "content": user_query})
        
        return self.chat_completion(messages, temperature=0.8, max_tokens=500)
    
    def get_program_recommendation(self, user_profile):
        """
        Get program recommendation based on user profile
        
        Args:
            user_profile (dict): User profile with experience, capital, etc.
            
        Returns:
            dict: Recommended program and explanation
        """
        prompt = f"""Based on the following trader profile, recommend the most suitable 
trading program from our offerings (One Phase, Two Phase, or Instant Funding):

Experience Level: {user_profile.get('experience', 'beginner')}
Preferred Capital: ${user_profile.get('preferred_capital', 10000)}
Risk Tolerance: {user_profile.get('risk_tolerance', 'moderate')}
Trading Style: {user_profile.get('trading_style', 'day trading')}

Provide a brief recommendation (2-3 sentences) explaining which program type 
would be best and why."""

        messages = [
            {"role": "system", "content": "You are a trading program advisor for MarketEdgePros."},
            {"role": "user", "content": prompt}
        ]
        
        return self.chat_completion(messages, temperature=0.7, max_tokens=300)
    
    @staticmethod
    def get_authorized_challenges(current_user, challenge_ids=None):
        """Return challenges owned by the authenticated user in their tenant.

        A challenge does not carry tenant metadata itself, so the tenant check
        must be made through its trading program. This returns ``None`` for
        malformed, missing, or inaccessible ownership metadata, allowing the
        route to use one not-found response for absent and forbidden resources.
        """
        user_id = getattr(current_user, 'id', None)
        tenant_id = getattr(current_user, 'tenant_id', None)
        if user_id is None or tenant_id is None:
            return None

        if challenge_ids is not None:
            if not isinstance(challenge_ids, (list, tuple, set)):
                return None
            challenge_ids = list(challenge_ids)
            if any(
                isinstance(challenge_id, bool)
                or not isinstance(challenge_id, int)
                or challenge_id <= 0
                for challenge_id in challenge_ids
            ):
                return None
            if len(set(challenge_ids)) != len(challenge_ids):
                return None

        try:
            from src.database import db
            from src.models import Challenge, TradingProgram

            query = db.session.query(Challenge).join(
                TradingProgram,
                Challenge.program_id == TradingProgram.id
            ).filter(
                Challenge.user_id == user_id,
                TradingProgram.tenant_id == tenant_id
            )
            if challenge_ids is not None:
                if not challenge_ids:
                    return []
                query = query.filter(Challenge.id.in_(challenge_ids))

            challenges = query.all()
            if challenge_ids is not None:
                found_ids = {challenge.id for challenge in challenges}
                if found_ids != set(challenge_ids):
                    return None
            return challenges
        except Exception:
            # Authorization cannot be established without the authoritative
            # lookup. Do not permit an AI call when that lookup fails.
            return None

    def analyze_trading_performance(
        self, performance_data, *, current_user=None, challenge_ids=None
    ):
        """
        Analyze trading performance and provide insights
        
        Args:
            performance_data (dict): Trading performance metrics
            current_user: Authenticated database user owning the challenges
            challenge_ids: Exact challenge IDs used to derive the metrics
            
        Returns:
            dict: Analysis and recommendations
        """
        # This independent check prevents a future caller from sending
        # performance data to OpenAI without proving its owner/tenant scope.
        if challenge_ids is None:
            return {
                'success': False,
                'not_found': True,
                'error': 'Resource not found'
            }
        authorized_challenges = self.get_authorized_challenges(
            current_user, challenge_ids
        )
        if not authorized_challenges:
            return {
                'success': False,
                'not_found': True,
                'error': 'Resource not found'
            }

        prompt = f"""Analyze the following trading performance and provide insights:

Total Trades: {performance_data.get('total_trades', 0)}
Win Rate: {performance_data.get('win_rate', 0)}%
Average Win: ${performance_data.get('avg_win', 0)}
Average Loss: ${performance_data.get('avg_loss', 0)}
Profit Factor: {performance_data.get('profit_factor', 0)}
Max Drawdown: {performance_data.get('max_drawdown', 0)}%

Provide:
1. Brief performance assessment
2. Key strengths
3. Areas for improvement
4. One actionable tip

Keep it concise (3-4 sentences)."""

        messages = [
            {"role": "system", "content": "You are a trading performance analyst."},
            {"role": "user", "content": prompt}
        ]
        
        return self.chat_completion(messages, temperature=0.6, max_tokens=400)
    
    def generate_faq_answer(self, question, context=None):
        """
        Generate answer for FAQ questions
        
        Args:
            question (str): FAQ question
            context (str): Optional context about the platform
            
        Returns:
            dict: Generated answer
        """
        system_message = """You are a customer support assistant for MarketEdgePros.
Answer questions about:
- Trading programs and rules
- Payment and payouts
- Platform features
- Account management
- General trading questions

Be clear, concise, and helpful. If you don't know something specific about 
MarketEdgePros policies, suggest contacting support."""

        messages = [
            {"role": "system", "content": system_message}
        ]
        
        if context:
            messages.append({"role": "system", "content": f"Context: {context}"})
        
        messages.append({"role": "user", "content": question})
        
        return self.chat_completion(messages, temperature=0.5, max_tokens=400)


# Singleton instance
_openai_service = None

def get_openai_service():
    """Get or create OpenAI service instance"""
    global _openai_service
    if _openai_service is None:
        _openai_service = OpenAIService()
    return _openai_service
