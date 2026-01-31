"""Retry queue for failed recipe imports"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable
from enum import Enum

logger = logging.getLogger(__name__)


class RetryStatus(Enum):
    """Status of retry task"""
    PENDING = "pending"
    RETRYING = "retrying"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class RetryTask:
    """Task to retry"""
    task_id: str
    user_id: int
    url: str
    attempt: int = 0
    max_attempts: int = 3
    next_retry: datetime = field(default_factory=datetime.now)
    status: RetryStatus = RetryStatus.PENDING
    last_error: Optional[str] = None
    
    def should_retry(self) -> bool:
        """Check if task should be retried"""
        return (
            self.attempt < self.max_attempts 
            and self.status != RetryStatus.SUCCESS
            and datetime.now() >= self.next_retry
        )
    
    def get_next_retry_delay(self) -> int:
        """Get delay in minutes for next retry (exponential backoff)"""
        delays = [5, 15, 30]  # 5 min, 15 min, 30 min
        if self.attempt < len(delays):
            return delays[self.attempt]
        return 30  # Default to 30 min


class RetryQueue:
    """Queue for retrying failed recipe imports"""
    
    def __init__(self):
        self.tasks: dict[str, RetryTask] = {}
        self.running = False
        self._processor_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start processing queue"""
        if not self.running:
            self.running = True
            self._processor_task = asyncio.create_task(self._process_queue())
            logger.info("Retry queue processor started")
    
    async def stop(self):
        """Stop processing queue"""
        self.running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        logger.info("Retry queue processor stopped")
    
    def add_task(self, task_id: str, user_id: int, url: str) -> RetryTask:
        """Add task to retry queue"""
        task = RetryTask(
            task_id=task_id,
            user_id=user_id,
            url=url,
            next_retry=datetime.now() + timedelta(minutes=5)  # First retry in 5 min
        )
        self.tasks[task_id] = task
        logger.info(f"Added task {task_id} to retry queue for user {user_id}, URL: {url}")
        return task
    
    def get_task(self, task_id: str) -> Optional[RetryTask]:
        """Get task by ID"""
        return self.tasks.get(task_id)
    
    def get_user_tasks(self, user_id: int) -> list[RetryTask]:
        """Get all tasks for a user"""
        return [task for task in self.tasks.values() if task.user_id == user_id]
    
    def remove_task(self, task_id: str):
        """Remove task from queue"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            logger.info(f"Removed task {task_id} from retry queue")
    
    async def _process_queue(self):
        """Process retry queue in background"""
        while self.running:
            try:
                # Check for tasks that need retry
                now = datetime.now()
                for task in list(self.tasks.values()):
                    if task.should_retry():
                        logger.info(f"Task {task.task_id} ready for retry (attempt {task.attempt + 1}/{task.max_attempts})")
                        # Task will be retried by external handler
                        # We just mark it as ready
                        task.status = RetryStatus.RETRYING
                
                # Sleep for 30 seconds before next check
                await asyncio.sleep(30)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in retry queue processor: {e}")
                await asyncio.sleep(30)
    
    def update_task_status(
        self, 
        task_id: str, 
        status: RetryStatus, 
        error: Optional[str] = None
    ):
        """Update task status after retry attempt"""
        task = self.get_task(task_id)
        if not task:
            return
        
        task.status = status
        task.attempt += 1
        
        if error:
            task.last_error = error
        
        if status == RetryStatus.SUCCESS:
            logger.info(f"Task {task_id} completed successfully after {task.attempt} attempts")
        elif status == RetryStatus.FAILED and task.attempt >= task.max_attempts:
            logger.error(f"Task {task_id} failed after {task.max_attempts} attempts")
        elif status == RetryStatus.PENDING:
            # Schedule next retry
            delay = task.get_next_retry_delay()
            task.next_retry = datetime.now() + timedelta(minutes=delay)
            logger.info(f"Task {task_id} will retry in {delay} minutes")
