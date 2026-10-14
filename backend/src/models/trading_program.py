"""
Trading Program and Challenge models
"""
from src.database import db, TimestampMixin
from sqlalchemy.dialects.postgresql import JSONB
from decimal import Decimal
from datetime import datetime, date
import pytz
from sqlalchemy.orm.attributes import flag_modified
from src.services.program_evaluation_policy import legacy_challenge_terms, public_program_rules

# Calculation method constants
CALC_METHOD_FTMO = 'ftmo'
CALC_METHOD_FXIFY = 'fxify'
CALC_METHOD_THE5ERS = 'the5ers'

# Timezone constants
TIMEZONE_CEST = 'Europe/Prague'
TIMEZONE_EST = 'US/Eastern'
TIMEZONE_MT5 = 'Europe/Athens'


class TradingProgram(db.Model, TimestampMixin):
    """Trading program/challenge type"""
    
    __tablename__ = 'trading_programs'
    
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    
    # Program Details
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # one_phase, two_phase, three_phase, instant_funding, lightning
    description = db.Column(db.Text)
    
    # Account Sizes
    account_size = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Targets and Limits
    profit_target = db.Column(db.Numeric(5, 2))  # Percentage
    max_daily_loss = db.Column(db.Numeric(5, 2))  # Percentage
    max_total_loss = db.Column(db.Numeric(5, 2))  # Percentage
    
    # Pricing
    price = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Profit Split
    profit_split = db.Column(db.Numeric(5, 2), default=80.00)  # Percentage to trader
    profit_split_percentage = db.Column(db.Numeric(5, 2), default=80.00)  # Alias for compatibility
    minimum_payout_amount = db.Column(db.Numeric(10, 2), default=50.00)  # Minimum payout
    payout_mode = db.Column(db.String(50), default="on_demand")  # on_demand, on_demand_rules, scheduled
    
    # Trading Rules (stored as JSON)
    rules = db.Column(JSONB, default={})
    
    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Relationships
    tenant = db.relationship('Tenant', back_populates='programs')
    challenges = db.relationship('Challenge', back_populates='program', lazy='dynamic')
    addons = db.relationship("ProgramAddOn", back_populates="program", lazy="dynamic")

    # Add indexes for performance
    __table_args__ = (db.Index("ix_trading_program_tenant_id", "tenant_id"),)
    
    def __repr__(self):
        return f'<TradingProgram {self.name}>'
    
    def calculate_total_price(self, addon_ids=None):
        """Calculate total price with add-ons"""
        total = self.price
        
        if addon_ids:
            addons = ProgramAddOn.query.filter(
                ProgramAddOn.id.in_(addon_ids),
                ProgramAddOn.program_id == self.id,
                ProgramAddOn.is_active == True
            ).all()
            
            for addon in addons:
                if addon.price_type == 'fixed':
                    total += addon.price
                elif addon.price_type == 'percentage':
                    total += (self.price * addon.price / 100)
        
        return total
    
    def to_dict(self):
        """Convert program to dictionary"""
        return {
            'id': self.id,
            'tenant_id': self.tenant_id,
            'name': self.name,
            'type': self.type,
            'description': self.description,
            'account_size': float(self.account_size),
            'profit_target': float(self.profit_target) if self.profit_target else None,
            'max_daily_loss': float(self.max_daily_loss) if self.max_daily_loss else None,
            'max_total_loss': float(self.max_total_loss) if self.max_total_loss else None,
            'price': float(self.price),
            'profit_split': float(self.profit_split),
            # Never expose challenge identifiers from the reserved private
            # history map. All other legacy JSON vocabulary remains unchanged.
            'rules': public_program_rules(self.rules),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class ProgramAddOn(db.Model, TimestampMixin):
    """Add-ons for trading programs"""
    
    __tablename__ = 'program_addons'
    
    id = db.Column(db.Integer, primary_key=True)
    program_id = db.Column(db.Integer, db.ForeignKey('trading_programs.id'), nullable=False)
    
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    # Pricing
    price = db.Column(db.Numeric(10, 2), nullable=False)
    price_type = db.Column(db.String(20), default='fixed')  # fixed, percentage
    
    # Benefits (stored as JSON)
    benefits = db.Column(JSONB, default={})
    
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    
    # Relationships
    program = db.relationship('TradingProgram', back_populates='addons')
    
    def __repr__(self):
        return f'<ProgramAddOn {self.name}>'
    
    def to_dict(self):
        """Convert add-on to dictionary"""
        return {
            'id': self.id,
            'program_id': self.program_id,
            'name': self.name,
            'description': self.description,
            'price': float(self.price),
            'price_type': self.price_type,
            'benefits': self.benefits,
            'is_active': self.is_active
        }


class Challenge(db.Model, TimestampMixin):
    """User's trading challenge"""
    
    __tablename__ = 'challenges'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('trading_programs.id'), nullable=False)
    
    # Challenge Status
    status = db.Column(db.String(20), default='pending', nullable=False)
    # pending, active, passed, failed, funded
    
    # Dates
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    passed_at = db.Column(db.DateTime)
    
    # Trading Account Details
    account_number = db.Column(db.String(50))
    initial_balance = db.Column(db.Numeric(12, 2))
    current_balance = db.Column(db.Numeric(12, 2))
    
    # Performance Metrics
    total_profit = db.Column(db.Numeric(12, 2), default=0)
    total_loss = db.Column(db.Numeric(12, 2), default=0)
    max_drawdown = db.Column(db.Numeric(12, 2), default=0)
    
    # Progress
    current_phase = db.Column(db.Integer, default=1)
    total_phases = db.Column(db.Integer, default=1)
    
    # Payment
    payment_status = db.Column(db.String(20), default='pending')  # pending, paid, refunded
    payment_id = db.Column(db.String(100))
    payment_type = db.Column(db.String(20), default='credit_card', nullable=False)  # credit_card, cash, free
    
    # Approval system (for cash/free payments)
    approval_status = db.Column(db.String(20), default='approved', nullable=False)  # pending, approved, rejected
    approved_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    approved_at = db.Column(db.DateTime)
    rejection_reason = db.Column(db.Text)
    
    # Creator tracking
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))  # Who created this challenge (for cash payments)
    
    # Add-ons purchased
    addons = db.Column(JSONB, default=[])
    daily_drawdown_history = db.Column(JSONB, default={})
    
    # Relationships
    user = db.relationship('User', back_populates='challenges', foreign_keys=[user_id])
    creator = db.relationship('User', back_populates='created_challenges', foreign_keys=[created_by])
    approver = db.relationship('User', foreign_keys=[approved_by])
    program = db.relationship("TradingProgram", back_populates="challenges")

    # Add indexes for performance
    __table_args__ = (db.Index("ix_challenge_user_id", "user_id"), db.Index("ix_challenge_status", "status"))
    
    def __repr__(self):
        return f'<Challenge {self.id} - User {self.user_id}>'

    def _archived_terms(self):
        """Return ``(terms, archived)`` for this immutable legacy binding.

        A matching malformed archive deliberately returns ``(None, True)`` so
        calculations do not silently switch to a later edited program row.
        """
        if not self.program:
            return None, False
        lookup = legacy_challenge_terms(self.program.rules, self.id)
        if isinstance(self.program.rules, dict) and "_mep_legacy_challenge_terms" in self.program.rules and not lookup.valid:
            return None, True
        if lookup.found:
            return lookup.terms if lookup.valid else None, True
        return None, False

    @staticmethod
    def _term_decimal(value):
        if value is None or isinstance(value, bool) or isinstance(value, float):
            return None
        try:
            result = Decimal(value)
        except Exception:
            return None
        return result if result.is_finite() else None

    def historical_program_term(self, field):
        """Read one archived program scalar, preserving old fallback semantics."""
        terms, archived = self._archived_terms()
        if archived:
            return None if terms is None else terms.get(field)
        return getattr(self.program, field, None) if self.program else None

    def historical_program_rules(self):
        """Read archived rules for a matching challenge, never current rules on error."""
        terms, archived = self._archived_terms()
        if archived:
            return None if terms is None else terms.get('rules')
        return self.program.rules if self.program else None

    def historical_program_read_fields(self):
        """Return serializer-compatible archived values for a matched snapshot.

        Existing program DTOs use floats for numeric columns.  This helper keeps
        that legacy wire shape while substituting only the values which belong to
        the historical challenge rather than an edited current program row.
        ``None`` values on a malformed matched archive are intentional: callers
        must not fall back to newly assigned catalog terms.
        """
        terms, archived = self._archived_terms()
        if not archived:
            return None
        fields = ('profit_target', 'max_daily_loss', 'max_total_loss', 'profit_split', 'profit_split_percentage')
        if terms is None:
            return {**{field: None for field in fields}, 'rules': None, 'name': None, 'type': None, 'description': None}
        # A revised description can include new stage targets or profit splits.
        # It must not be inherited by a historical challenge with archived terms.
        result = {field: terms.get(field) for field in ('name', 'type', 'description')}
        for field in fields:
            value = self._term_decimal(terms.get(field))
            result[field] = float(value) if value is not None else None
        # The archived nested rules are independently bounded/validated when
        # the private map is read. Strip the same reserved key defensively if a
        # historic rules object itself contains one.
        result['rules'] = public_program_rules(terms['rules'])
        return result
    
    def calculate_progress(self):
        """Calculate challenge progress percentage"""
        target_percent = self._term_decimal(self.historical_program_term('profit_target'))
        if target_percent is None or target_percent == 0:
            return 0

        initial_balance = self._term_decimal(self.initial_balance)
        total_profit = self._term_decimal(self.total_profit)
        if initial_balance is None or total_profit is None:
            return 0
        target_profit = (initial_balance * target_percent / 100)
        if target_profit == 0:
            return 0

        progress = (total_profit / target_profit) * 100
        return min(progress, 100)
    
    def is_target_reached(self):
        """Check if profit target is reached"""
        return self.calculate_progress() >= 100
    
    def get_calculation_method(self):
        """Get calculation method from program settings"""
        rules = self.historical_program_rules()
        if not isinstance(rules, dict):
            return CALC_METHOD_FTMO
        return rules.get('calculation_method', CALC_METHOD_FTMO)
    
    def get_timezone(self):
        """Get timezone based on calculation method"""
        method = self.get_calculation_method()
        if method == CALC_METHOD_FTMO:
            return pytz.timezone(TIMEZONE_CEST)
        elif method == CALC_METHOD_FXIFY:
            return pytz.timezone(TIMEZONE_EST)
        elif method == CALC_METHOD_THE5ERS:
            return pytz.timezone(TIMEZONE_MT5)
        return pytz.timezone(TIMEZONE_CEST)
    
    def get_reset_time(self):
        """Get reset time based on calculation method"""
        method = self.get_calculation_method()
        if method == CALC_METHOD_FTMO:
            return {'hour': 0, 'minute': 0}
        elif method == CALC_METHOD_FXIFY:
            return {'hour': 17, 'minute': 0}
        elif method == CALC_METHOD_THE5ERS:
            return {'hour': 0, 'minute': 0}
        return {'hour': 0, 'minute': 0}
    
    def get_current_date(self):
        """Get current date in the appropriate timezone"""
        tz = self.get_timezone()
        return datetime.now(tz).date().isoformat()
    
    def should_reset_daily_data(self):
        """Check if daily data should be reset based on reset time"""
        tz = self.get_timezone()
        reset_time = self.get_reset_time()
        now = datetime.now(tz)
        today = now.date().isoformat()
        
        if not self.daily_drawdown_history or today not in self.daily_drawdown_history:
            return True
        
        reset_datetime = now.replace(
            hour=reset_time['hour'],
            minute=reset_time['minute'],
            second=0,
            microsecond=0
        )
        
        day_data = self.daily_drawdown_history[today]
        last_update = day_data.get('last_update')
        
        if not last_update:
            return True
        
        last_update_dt = datetime.fromisoformat(last_update)
        if last_update_dt < reset_datetime <= now:
            return True
        
        return False
    
    def calculate_starting_value(self, balance, equity):
        """Calculate starting value based on calculation method"""
        method = self.get_calculation_method()
        
        if method == CALC_METHOD_FTMO:
            return float(balance)
        elif method == CALC_METHOD_FXIFY:
            return float(balance)
        elif method == CALC_METHOD_THE5ERS:
            return max(float(equity), float(balance))
        return float(balance)
    
    def is_max_loss_exceeded(self):
        """FIXED: Check if maximum total loss limit is exceeded"""
        maximum_loss = self._term_decimal(self.historical_program_term('max_total_loss'))
        if maximum_loss is None or maximum_loss == 0:
            return False
        
        if not self.initial_balance:
            return False
        
        # Calculate max allowed loss amount
        max_loss_pct = float(maximum_loss) / 100
        max_loss_amount = float(self.initial_balance) * max_loss_pct
        
        # Check if total_loss (absolute value) exceeds max
        if self.total_loss is not None:
            actual_loss = abs(float(self.total_loss))
            if actual_loss >= max_loss_amount:
                return True
        
        # Also check current equity as fallback
        today = self.get_current_date()
        
        # Get current equity
        if self.daily_drawdown_history and today in self.daily_drawdown_history:
            current_equity = self.daily_drawdown_history[today].get('current_equity', self.current_balance)
        else:
            current_equity = self.current_balance
        
        # Calculate threshold from initial balance
        threshold = float(self.initial_balance) - max_loss_amount
        
        return float(current_equity) <= threshold

    def is_daily_loss_exceeded(self):
        """FIXED: Check if daily loss limit is exceeded (industry-standard)"""
        maximum_daily_loss = self._term_decimal(self.historical_program_term('max_daily_loss'))
        if maximum_daily_loss is None or maximum_daily_loss == 0:
            return False
        
        today = self.get_current_date()
        
        if not self.daily_drawdown_history or today not in self.daily_drawdown_history:
            return False
        
        day_data = self.daily_drawdown_history[today]
        
        # FIXED: Use equity and threshold (not loss amount!)
        current_equity = day_data.get('current_equity', 0)
        threshold = day_data.get('threshold', 0)
        
        if threshold > 0 and current_equity <= threshold:
            return True
        
        return False
    
    def update_daily_drawdown(self, current_balance, current_equity=None, open_pnl=0, commissions=0, swaps=0):
        """FIXED: Track daily drawdown with industry-standard calculations"""
        today = self.get_current_date()
        
        # Calculate equity if not provided
        if current_equity is None:
            current_equity = float(current_balance) + float(open_pnl)
        else:
            current_equity = float(current_equity)
        
        current_balance = float(current_balance)
        open_pnl = float(open_pnl)
        commissions = float(commissions)
        swaps = float(swaps)
        
        # Initialize if needed
        if not self.daily_drawdown_history:
            self.daily_drawdown_history = {}
        
        # Check if we need to reset
        if self.should_reset_daily_data():
            starting_value = self.calculate_starting_value(current_balance, current_equity)
            
            self.daily_drawdown_history[today] = {
                'starting_balance': current_balance,
                'starting_equity': current_equity,
                'starting_value': starting_value,
                'current_balance': current_balance,
                'current_equity': current_equity,
                'open_pnl': open_pnl,
                'closed_pnl': 0,
                'max_balance': current_balance,
                'max_equity': current_equity,
                'min_balance': current_balance,
                'min_equity': current_equity,
                'loss_from_start': 0,
                'loss_from_peak': 0,
                'commissions': commissions,
                'swaps': swaps,
                'daily_limit': 0,
                'threshold': 0,
                'calculation_method': self.get_calculation_method(),
                'timezone': str(self.get_timezone()),
                'reset_time': datetime.now(self.get_timezone()).replace(
                    hour=self.get_reset_time()['hour'],
                    minute=self.get_reset_time()['minute']
                ).isoformat(),
                'last_update': datetime.now(self.get_timezone()).isoformat()
            }
            
            # Calculate daily limit
            maximum_daily_loss = self._term_decimal(self.historical_program_term('max_daily_loss'))
            if maximum_daily_loss is not None and maximum_daily_loss != 0:
                daily_loss_pct = float(maximum_daily_loss) / 100
                daily_limit = starting_value * daily_loss_pct
                threshold = starting_value - daily_limit
                
                self.daily_drawdown_history[today]['daily_limit'] = daily_limit
                self.daily_drawdown_history[today]['threshold'] = threshold
        
        # Update today's data
        day_data = self.daily_drawdown_history[today]
        
        day_data['current_balance'] = current_balance
        day_data['current_equity'] = current_equity
        day_data['open_pnl'] = open_pnl
        day_data['commissions'] += commissions
        day_data['swaps'] += swaps
        
        # Update max/min
        if current_balance > day_data['max_balance']:
            day_data['max_balance'] = current_balance
        if current_balance < day_data['min_balance']:
            day_data['min_balance'] = current_balance
        if current_equity > day_data['max_equity']:
            day_data['max_equity'] = current_equity
        if current_equity < day_data['min_equity']:
            day_data['min_equity'] = current_equity
        
        # Calculate closed P/L
        day_data['closed_pnl'] = current_balance - day_data['starting_balance']
        
        # Calculate losses (FIXED!)
        day_data['loss_from_start'] = max(0, day_data['starting_value'] - current_equity)
        day_data['loss_from_peak'] = max(0, day_data['max_equity'] - current_equity)
        
        # Calculate drawdown percentage
        if day_data['max_equity'] > 0:
            day_data['drawdown_pct'] = (day_data['loss_from_peak'] / day_data['max_equity']) * 100
        else:
            day_data['drawdown_pct'] = 0
        
        day_data['last_update'] = datetime.now(self.get_timezone()).isoformat()
        
        self.daily_drawdown_history[today] = day_data
        flag_modified(self, 'daily_drawdown_history')
        
        return day_data
    
    def check_challenge_rules(self):
        """Check all challenge rules and update status"""
        from datetime import datetime
        
        if self.status not in ['active', 'in_progress']:
            return
        
        # Check if profit target reached
        if self.is_target_reached():
            self.status = 'passed'
            self.passed_at = datetime.utcnow()
            return
        
        # Check if max total loss exceeded
        if self.is_max_loss_exceeded():
            self.status = 'failed'
            self.failed_at = datetime.utcnow()
            self.failure_reason = 'Max total loss exceeded'
            return
        
        # Check if daily loss exceeded
        if self.is_daily_loss_exceeded():
            self.status = 'failed'
            self.failed_at = datetime.utcnow()
            self.failure_reason = 'Daily loss limit exceeded'
            return
        
        # Check if expired
        if self.end_date and datetime.utcnow() > self.end_date:
            if not self.is_target_reached():
                self.status = 'failed'
                self.failed_at = datetime.utcnow()
                self.failure_reason = 'Time expired'
            else:
                self.status = 'passed'
                self.passed_at = datetime.utcnow()
    
    def get_daily_stats(self):
        """Get current day's statistics"""
        today = self.get_current_date()
        
        if not self.daily_drawdown_history or today not in self.daily_drawdown_history:
            return None
        
        day_data = self.daily_drawdown_history[today]
        
        threshold = day_data.get('threshold', 0)
        current_equity = day_data.get('current_equity', 0)
        remaining_room = current_equity - threshold if threshold > 0 else 0
        
        starting_value = day_data.get('starting_value', 0)
        daily_pnl = current_equity - starting_value
        daily_pnl_pct = (daily_pnl / starting_value * 100) if starting_value > 0 else 0
        
        return {
            'date': today,
            'starting_value': day_data.get('starting_value', 0),
            'starting_balance': day_data.get('starting_balance', 0),
            'starting_equity': day_data.get('starting_equity', 0),
            'current_balance': day_data.get('current_balance', 0),
            'current_equity': current_equity,
            'open_pnl': day_data.get('open_pnl', 0),
            'closed_pnl': day_data.get('closed_pnl', 0),
            'daily_pnl': daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'max_equity': day_data.get('max_equity', 0),
            'min_equity': day_data.get('min_equity', 0),
            'loss_from_start': day_data.get('loss_from_start', 0),
            'loss_from_peak': day_data.get('loss_from_peak', 0),
            'drawdown_pct': day_data.get('drawdown_pct', 0),
            'daily_limit': day_data.get('daily_limit', 0),
            'threshold': threshold,
            'remaining_room': remaining_room,
            'commissions': day_data.get('commissions', 0),
            'swaps': day_data.get('swaps', 0),
            'calculation_method': day_data.get('calculation_method', 'ftmo'),
            'is_daily_loss_exceeded': self.is_daily_loss_exceeded(),
            'is_max_loss_exceeded': self.is_max_loss_exceeded()
        }
    
    def to_dict(self):
        """Convert challenge to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'program_id': self.program_id,
            'status': self.status,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'account_number': self.account_number,
            'initial_balance': float(self.initial_balance) if self.initial_balance else None,
            'current_balance': float(self.current_balance) if self.current_balance else None,
            'total_profit': float(self.total_profit),
            'total_loss': float(self.total_loss),
            'max_drawdown': float(self.max_drawdown),
            'current_phase': self.current_phase,
            'total_phases': self.total_phases,
            'payment_status': self.payment_status,
            'payment_type': self.payment_type,
            'approval_status': self.approval_status,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'rejection_reason': self.rejection_reason,
            'created_by': self.created_by,
            'progress': self.calculate_progress(),
            'addons': self.addons,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
