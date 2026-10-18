"""Hierarchy criteria on real isolated PostgreSQL, with synthetic records only."""
from sqlalchemy import select, text, update
from sqlalchemy.orm import aliased
import pytest


def seed_hierarchy(app):
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.user import User
    with app.app_context():
        db.session.add_all([Tenant(id=1,name='A',subdomain='a'),Tenant(id=2,name='B',subdomain='b')])
        db.session.flush()
        for identity,parent,path,tenant in [(1,None,'1',1),(2,1,'1/2',1),(3,1,'1/20',1),(4,2,'1/2/4',2),(5,2,'1/2/5',1)]:
            db.session.add(User(id=identity,parent_id=parent,tree_path=path,tenant_id=tenant,
                role='master' if identity<3 else 'trader',email=f'pg-hierarchy-{identity}@example.invalid',
                password_hash='synthetic-not-a-credential',first_name='Synthetic',last_name='Hierarchy'))
            db.session.flush()
        db.session.commit()


def test_postgresql_hierarchy_alias_and_cross_tenant_bulk_refusal(app):
    from src.database import db
    from src.models.user import User
    from src.utils.hierarchy_scoping import set_request_hierarchy_scope
    seed_hierarchy(app)
    with app.test_request_context():
        set_request_hierarchy_scope(db.session,db.session.get(User,2))
        assert set(db.session.execute(select(User.id)).scalars())=={2,5}
        user_alias=aliased(User)
        assert set(db.session.execute(select(user_alias.id)).scalars())=={2,5}
        statement=update(User).where(User.id==4).values(first_name='DENIED')
        assert db.session.execute(statement.execution_options(synchronize_session=False)).rowcount==0
        db.session.commit()
    with app.app_context():
        assert db.session.get(User,4).first_name=='Synthetic'
        assert User.query.count()==5


def test_postgresql_stored_cycle_raises_before_unbounded_ancestry(app):
    from src.database import db
    from src.models.user import User
    seed_hierarchy(app)
    with app.app_context():
        # Synthetic corruption bypasses ORM guards; no business data is involved.
        db.session.execute(text('UPDATE users SET parent_id=5 WHERE id=1'))
        db.session.commit()
        db.session.expire_all()
        with pytest.raises(ValueError,match='cycle'):
            db.session.get(User,5).get_ancestors()
