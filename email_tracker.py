"""
Email Tracking Database Helper
Tracks all bid invitation emails sent through the system
"""

import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import asyncpg
from clients.buildingconnected_client import BiddingInvitationData, Project
from sentry_config import (
    set_database_context, add_breadcrumb, capture_exception_with_context,
    SentryOperations, SentryComponents, SentrySeverity
)

logger = logging.getLogger(__name__)


class EmailTracker:
    """Database helper for tracking email sends"""
    
    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or os.getenv("DATABASE_URL")
        if not self.database_url:
            logger.error("❌ DATABASE_URL environment variable not set")
            raise ValueError("DATABASE_URL environment variable not set")
        logger.info(f"📋 EmailTracker initialized with database: {self.database_url[:50]}...")
    
    async def create_table_if_not_exists(self):
        """Create the email tracking table if it doesn't exist"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS email_tracking (
            id SERIAL PRIMARY KEY,
            projectid VARCHAR(255) NOT NULL,
            bidpackageid VARCHAR(255) NOT NULL,
            firstname VARCHAR(255),
            lastname VARCHAR(255),
            inviteid VARCHAR(255) NOT NULL,
            title VARCHAR(255),
            email VARCHAR(255) NOT NULL,
            company VARCHAR(255),
            projectname VARCHAR(255),
            bidpackagename VARCHAR(255),
            bidinvitelink TEXT,
            bidsdueat TIMESTAMP,
            daysuntilbidsdue INTEGER,
            sentat TIMESTAMP NOT NULL DEFAULT NOW(),
            status VARCHAR(50) NOT NULL
        );
        """
        
        try:
            logger.info("🔌 Connecting to database for table creation...")
            conn = await asyncpg.connect(self.database_url)
            logger.info("✅ Database connection established")
            await conn.execute(create_table_sql)
            await conn.close()
            logger.info("✅ Email tracking table created/verified successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create email tracking table: {str(e)}")
            logger.error(f"   Database URL: {self.database_url[:50]}...")
            raise
    
    async def log_email_attempt(
        self,
        invitation: BiddingInvitationData,
        project: Optional[Project],
        status: str,
        company: Optional[str] = None
    ) -> int:
        """
        Log an email attempt to the database
        
        Args:
            invitation: The bidding invitation data
            project: The project data (optional)
            status: 'SUCCESS' or 'FAILED'
            company: Company name (if available)
            
        Returns:
            The ID of the inserted record
        """
        # Set database context for email logging
        set_database_context("insert", "email_tracking")
        
        add_breadcrumb(
            message=f"Logging email attempt: {status}",
            category="database",
            level="info",
            data={
                "operation": "log_email",
                "table": "email_tracking",
                "email": invitation.email,
                "status": status
            }
        )
        
        logger.debug(f"📝 Logging email attempt for {invitation.email} with status {status}")
        
        try:
            # Parse the bids due date (convert to naive UTC for database)
            bids_due_at = None
            if invitation.bidsDueAt:
                try:
                    bids_due_at = datetime.fromisoformat(invitation.bidsDueAt.replace('Z', '+00:00'))
                    # Convert to naive UTC datetime for PostgreSQL compatibility
                    if bids_due_at.tzinfo is not None:
                        bids_due_at = bids_due_at.astimezone(timezone.utc).replace(tzinfo=None)
                except:
                    logger.warning(f"Failed to parse bidsDueAt: {invitation.bidsDueAt}")
            
            # Prepare the data (use naive UTC datetime for database compatibility)
            sent_at = datetime.now(timezone.utc).replace(tzinfo=None)  # Convert to naive UTC
            
            data = {
                'projectid': invitation.projectId,
                'bidpackageid': invitation.bidPackageId,
                'firstname': invitation.firstName or '',
                'lastname': invitation.lastName or '',
                'inviteid': invitation.id,
                'title': invitation.title or '',
                'email': invitation.email,
                'company': company or '',
                'projectname': project.name if project else '',
                'bidpackagename': invitation.bidPackageName,
                'bidinvitelink': invitation.linkToBid,
                'bidsdueat': bids_due_at,
                'daysuntilbidsdue': invitation.daysUntilBidsDue,
                'sentat': sent_at,
                'status': status
            }
            
            # Insert the record
            insert_sql = """
            INSERT INTO email_tracking (
                projectid, bidpackageid, firstname, lastname, inviteid, title, 
                email, company, projectname, bidpackagename, bidinvitelink, 
                bidsdueat, daysuntilbidsdue, sentat, status
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
            ) RETURNING id;
            """
            
            logger.info(f"🔌 Connecting to database to log email: {invitation.email}")
            conn = await asyncpg.connect(self.database_url)
            logger.info("✅ Database connection established for email logging")
            
            logger.info(f"📝 Inserting email record with data: {data['email']}, {data['status']}, {data['projectname']}")
            record_id = await conn.fetchval(
                insert_sql,
                data['projectid'], data['bidpackageid'], data['firstname'], 
                data['lastname'], data['inviteid'], data['title'], data['email'], 
                data['company'], data['projectname'], data['bidpackagename'], 
                data['bidinvitelink'], data['bidsdueat'], data['daysuntilbidsdue'], 
                data['sentat'], data['status']
            )
            await conn.close()
            logger.info("🔐 Database connection closed")
            
            logger.info(f"✅ Email tracking record created: ID {record_id}, Status: {status}, Email: {invitation.email}")
            
            add_breadcrumb(
                message="Email attempt logged successfully",
                category="database",
                level="info",
                data={
                    "operation": "log_email",
                    "table": "email_tracking",
                    "record_id": record_id,
                    "email": invitation.email,
                    "status": status
                }
            )
            
            return record_id
            
        except Exception as e:
            logger.error(f"❌ Failed to log email attempt: {str(e)}")
            logger.error(f"   Invitation ID: {invitation.id}")
            logger.error(f"   Email: {invitation.email}")
            logger.error(f"   Status: {status}")
            
            capture_exception_with_context(
                e,
                operation=SentryOperations.DATABASE_OPERATION,
                component=SentryComponents.DATABASE,
                severity=SentrySeverity.HIGH,
                extra_context={
                    "db_operation": "log_email_attempt",
                    "table": "email_tracking",
                    "invitation_id": invitation.id,
                    "email": invitation.email,
                    "status": status
                }
            )
            
            raise
    
    async def get_email_stats(self) -> Dict[str, Any]:
        """Get email sending statistics"""
        # Set database context for stats query
        set_database_context("select", "email_tracking")
        
        add_breadcrumb(
            message="Getting email statistics",
            category="database",
            level="info",
            data={"operation": "get_stats", "table": "email_tracking"}
        )
        
        logger.debug("📊 Getting email sending statistics")
        
        try:
            conn = await asyncpg.connect(self.database_url)
            
            # Get total counts by status
            stats_sql = """
            SELECT 
                status,
                COUNT(*) as count,
                COUNT(DISTINCT email) as unique_recipients,
                COUNT(DISTINCT projectid) as unique_projects
            FROM email_tracking
            GROUP BY status
            ORDER BY status;
            """
            
            rows = await conn.fetch(stats_sql)
            await conn.close()
            
            stats = {
                'by_status': [dict(row) for row in rows],
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Failed to get email stats: {str(e)}")
            
            capture_exception_with_context(
                e,
                operation=SentryOperations.DATABASE_OPERATION,
                component=SentryComponents.DATABASE,
                severity=SentrySeverity.MEDIUM,
                extra_context={
                    "db_operation": "get_email_stats",
                    "table": "email_tracking"
                }
            )
            
            return {'error': str(e)}
    
    async def get_recent_emails(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent email sends"""
        # Set database context for recent emails query
        set_database_context("select", "email_tracking")
        
        add_breadcrumb(
            message=f"Getting recent emails (limit: {limit})",
            category="database",
            level="info",
            data={"operation": "get_recent", "table": "email_tracking", "limit": limit}
        )
        
        logger.debug(f"📋 Getting recent {limit} email records")
        
        try:
            conn = await asyncpg.connect(self.database_url)
            
            recent_sql = """
            SELECT * FROM email_tracking
            ORDER BY sentat DESC
            LIMIT $1;
            """
            
            rows = await conn.fetch(recent_sql, limit)
            await conn.close()
            
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"❌ Failed to get recent emails: {str(e)}")
            
            capture_exception_with_context(
                e,
                operation=SentryOperations.DATABASE_OPERATION,
                component=SentryComponents.DATABASE,
                severity=SentrySeverity.MEDIUM,
                extra_context={
                    "db_operation": "get_recent_emails",
                    "table": "email_tracking",
                    "limit": limit
                }
            )
            
            return []
    
    async def get_email_attempts_for_contact(self, email: str, project_id: str) -> List[Dict[str, Any]]:
        """Get previous email attempts for a specific contact and project"""
        # Set database context for email attempts query
        set_database_context("select", "email_tracking")
        
        add_breadcrumb(
            message=f"Getting email attempts for contact and project",
            category="database",
            level="info",
            data={
                "operation": "get_email_attempts",
                "table": "email_tracking",
                "email": email,
                "project_id": project_id
            }
        )
        
        logger.debug(f"📋 Getting email attempts for {email} on project {project_id}")
        
        try:
            conn = await asyncpg.connect(self.database_url)
            
            attempts_sql = """
            SELECT * FROM email_tracking
            WHERE email = $1 AND projectid = $2
            ORDER BY sentat DESC;
            """
            
            rows = await conn.fetch(attempts_sql, email, project_id)
            await conn.close()
            
            logger.debug(f"Found {len(rows)} previous email attempts for {email} on project {project_id}")
            return [dict(row) for row in rows]
            
        except Exception as e:
            logger.error(f"❌ Failed to get email attempts for contact: {str(e)}")
            
            capture_exception_with_context(
                e,
                operation=SentryOperations.DATABASE_OPERATION,
                component=SentryComponents.DATABASE,
                severity=SentrySeverity.MEDIUM,
                extra_context={
                    "db_operation": "get_email_attempts_for_contact",
                    "table": "email_tracking",
                    "email": email,
                    "project_id": project_id
                }
            )
            
            return [] 