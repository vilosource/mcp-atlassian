"""Module for Jira worklog operations."""

import logging
import re
from typing import Any

from ..models import JiraWorklog
from ..utils import parse_date
from .client import JiraClient

logger = logging.getLogger("mcp-jira")


class WorklogMixin(JiraClient):
    """Mixin for Jira worklog operations."""

    def _parse_time_spent(self, time_spent: str) -> int:
        """
        Parse time spent string into seconds.

        Args:
            time_spent: Time spent string (e.g. 1h 30m, 1d, etc.)

        Returns:
            Time spent in seconds
        """
        # Base case for direct specification in seconds
        if time_spent.endswith("s"):
            try:
                return int(time_spent[:-1])
            except ValueError:
                pass

        total_seconds = 0
        time_units = {
            "w": 7 * 24 * 60 * 60,  # weeks to seconds
            "d": 24 * 60 * 60,  # days to seconds
            "h": 60 * 60,  # hours to seconds
            "m": 60,  # minutes to seconds
        }

        # Regular expression to find time components like 1w, 2d, 3h, 4m
        pattern = r"(\d+)([wdhm])"
        matches = re.findall(pattern, time_spent)

        for value, unit in matches:
            # Convert value to int and multiply by the unit in seconds
            seconds = int(value) * time_units[unit]
            total_seconds += seconds

        if total_seconds == 0:
            # If we couldn't parse anything, try using the raw value
            try:
                return int(float(time_spent))  # Convert to float first, then to int
            except ValueError:
                # If all else fails, default to 60 seconds (1 minute)
                logger.warning(
                    f"Could not parse time: {time_spent}, defaulting to 60 seconds"
                )
                return 60

        return total_seconds

    def add_worklog(
        self,
        issue_key: str,
        time_spent: str,
        comment: str | None = None,
        started: str | None = None,
        original_estimate: str | None = None,
        remaining_estimate: str | None = None,
    ) -> dict[str, Any]:
        """
        Add a worklog entry to a Jira issue.

        Args:
            issue_key: The issue key (e.g. 'PROJ-123')
            time_spent: Time spent (e.g. '1h 30m', '3h', '1d')
            comment: Optional comment for the worklog
            started: Optional ISO8601 date time string for when work began
            original_estimate: Optional new value for the original estimate
            remaining_estimate: Optional new value for the remaining estimate

        Returns:
            Response data if successful

        Raises:
            Exception: If there's an error adding the worklog
        """
        try:
            # Convert time_spent string to seconds
            time_spent_seconds = self._parse_time_spent(time_spent)

            # Convert Markdown comment to Jira format if provided
            if comment:
                # Check if _markdown_to_jira is available (from CommentsMixin)
                if hasattr(self, "_markdown_to_jira"):
                    comment = self._markdown_to_jira(comment)

            # Step 1: Update original estimate if provided (separate API call)
            original_estimate_updated = False
            if original_estimate:
                try:
                    fields = {"timetracking": {"originalEstimate": original_estimate}}
                    self.jira.edit_issue(issue_id_or_key=issue_key, fields=fields)
                    original_estimate_updated = True
                    logger.info(f"Updated original estimate for issue {issue_key}")
                except Exception as e:  # noqa: BLE001 - Intentional fallback with logging
                    logger.error(
                        f"Failed to update original estimate for issue {issue_key}: "
                        f"{str(e)}"
                    )
                    # Continue with worklog creation even if estimate update fails

            # Step 2: Prepare worklog data
            worklog_data: dict[str, Any] = {"timeSpentSeconds": time_spent_seconds}
            if comment:
                worklog_data["comment"] = comment
            if started:
                worklog_data["started"] = started

            # Step 3: Prepare query parameters for remaining estimate
            params = {}
            remaining_estimate_updated = False
            if remaining_estimate:
                params["adjustEstimate"] = "new"
                params["newEstimate"] = remaining_estimate
                remaining_estimate_updated = True

            # Step 4: Add the worklog with remaining estimate adjustment
            base_url = self.jira.resource_url("issue")
            url = f"{base_url}/{issue_key}/worklog"

            result = self.jira.post(url, data=worklog_data, params=params)
            if not isinstance(result, dict):
                msg = f"Unexpected return value type from `jira.post`: {type(result)}"
                logger.error(msg)
                raise TypeError(msg)

            # Format and return the result
            return {
                "id": result.get("id"),
                "comment": self._clean_text(result.get("comment", "")),
                "created": str(parse_date(result.get("created", ""))),
                "updated": str(parse_date(result.get("updated", ""))),
                "started": str(parse_date(result.get("started", ""))),
                "timeSpent": result.get("timeSpent", ""),
                "timeSpentSeconds": result.get("timeSpentSeconds", 0),
                "author": result.get("author", {}).get("displayName", "Unknown"),
                "original_estimate_updated": original_estimate_updated,
                "remaining_estimate_updated": remaining_estimate_updated,
            }
        except Exception as e:
            logger.error(f"Error adding worklog to issue {issue_key}: {str(e)}")
            raise Exception(f"Error adding worklog: {str(e)}") from e

    def get_worklog(self, issue_key: str) -> dict[str, Any]:
        """
        Get the worklog data for an issue.

        Args:
            issue_key: The issue key (e.g. 'PROJ-123')

        Returns:
            Raw worklog data from the API
        """
        try:
            return self.jira.worklog(issue_key)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"Error getting worklog for {issue_key}: {e}")
            return {"worklogs": []}

    def get_worklog_models(self, issue_key: str) -> list[JiraWorklog]:
        """
        Get all worklog entries for an issue as JiraWorklog models.

        Args:
            issue_key: The issue key (e.g. 'PROJ-123')

        Returns:
            List of JiraWorklog models
        """
        worklog_data = self.get_worklog(issue_key)
        result: list[JiraWorklog] = []

        if "worklogs" in worklog_data and worklog_data["worklogs"]:
            for log_data in worklog_data["worklogs"]:
                worklog = JiraWorklog.from_api_response(log_data)
                result.append(worklog)

        return result

    def get_worklogs(self, issue_key: str) -> list[dict[str, Any]]:
        """
        Get all worklog entries for an issue.

        Args:
            issue_key: The issue key (e.g. 'PROJ-123')

        Returns:
            List of worklog entries

        Raises:
            Exception: If there's an error getting the worklogs
        """
        try:
            result = self.jira.issue_get_worklog(issue_key)
            if not isinstance(result, dict):
                msg = f"Unexpected return value type from `jira.issue_get_worklog`: {type(result)}"
                logger.error(msg)
                raise TypeError(msg)

            # Process the worklogs
            worklogs = []
            for worklog in result.get("worklogs", []):
                worklogs.append(
                    {
                        "id": worklog.get("id"),
                        "comment": self._clean_text(worklog.get("comment", "")),
                        "created": str(parse_date(worklog.get("created", ""))),
                        "updated": str(parse_date(worklog.get("updated", ""))),
                        "started": str(parse_date(worklog.get("started", ""))),
                        "timeSpent": worklog.get("timeSpent", ""),
                        "timeSpentSeconds": worklog.get("timeSpentSeconds", 0),
                        "author": worklog.get("author", {}).get(
                            "displayName", "Unknown"
                        ),
                    }
                )

            return worklogs
        except Exception as e:
            logger.error(f"Error getting worklogs for issue {issue_key}: {str(e)}")
            raise Exception(f"Error getting worklogs: {str(e)}") from e

    def get_worklogs_updated_since(
        self, since_timestamp_ms: int, expand: str | None = None
    ) -> dict[str, Any]:
        """
        Get worklog IDs and update timestamps for worklogs updated after a timestamp.

        This uses the Jira REST API endpoint: GET /rest/api/3/worklog/updated
        which is NOT limited to 5000 results per issue and supports pagination.

        Args:
            since_timestamp_ms: UNIX timestamp in milliseconds after which
                to return updated worklogs
            expand: Optional expand parameter (e.g., 'properties')

        Returns:
            Dict containing 'values' list with worklog IDs and timestamps,
            plus pagination info
        """
        try:
            # NOTE: Cannot use self.jira.get_updated_worklogs() due to bug in
            # atlassian-python-api where it multiplies `since` by 1000 even
            # though the param is already in milliseconds, causing string
            # multiplication when passed as string. Using direct API call.
            url = self.jira.resource_url("worklog/updated")
            params: dict[str, Any] = {"since": since_timestamp_ms}
            if expand:
                params["expand"] = expand

            result = self.jira.get(url, params=params)
            if not isinstance(result, dict):
                return {"values": [], "lastPage": True}
            return result
        except Exception as e:  # noqa: BLE001 - Intentional fallback with logging
            logger.error(
                f"Error getting updated worklogs since {since_timestamp_ms}: {e}"
            )
            return {"values": [], "lastPage": True, "error": str(e)}

    def get_worklogs_by_ids(
        self, worklog_ids: list[int | str], expand: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Get full worklog details for a list of worklog IDs.

        This uses the Jira REST API endpoint: POST /rest/api/3/worklog/list
        which returns complete worklog information for the specified IDs.

        Args:
            worklog_ids: List of worklog IDs to retrieve
            expand: Optional expand parameter (e.g., 'properties')

        Returns:
            List of worklog entries with full details
        """
        if not worklog_ids:
            return []

        try:
            # Convert all IDs to integers (API expects int list)
            ids = [int(wid) for wid in worklog_ids]
            result = self.jira.get_worklogs(ids=ids, expand=expand)

            if not isinstance(result, list):
                logger.warning(
                    f"Unexpected result type from get_worklogs: {type(result)}"
                )
                return []

            # Process and format worklogs
            worklogs = []
            for worklog in result:
                author = worklog.get("author", {}).get("displayName", "Unknown")
                worklogs.append(
                    {
                        "id": worklog.get("id"),
                        "issueId": worklog.get("issueId"),
                        "comment": self._clean_text(worklog.get("comment", "")),
                        "created": str(parse_date(worklog.get("created", ""))),
                        "updated": str(parse_date(worklog.get("updated", ""))),
                        "started": str(parse_date(worklog.get("started", ""))),
                        "timeSpent": worklog.get("timeSpent", ""),
                        "timeSpentSeconds": worklog.get("timeSpentSeconds", 0),
                        "author": author,
                    }
                )

            return worklogs
        except Exception as e:  # noqa: BLE001 - Intentional fallback with logging
            logger.error(f"Error getting worklogs by IDs: {e}")
            return []

    def get_worklogs_by_date_range(
        self,
        since_date: str,
        until_date: str | None = None,
        author_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all worklogs updated within a date range, optionally filtered by author.

        This bypasses the 5000-result limit of per-issue worklog queries by using
        the global worklog/updated API instead.

        Args:
            since_date: Start date in ISO format (YYYY-MM-DD) or datetime
            until_date: Optional end date in ISO format (YYYY-MM-DD) or datetime.
                       If not provided, returns all worklogs up to now.
            author_filter: Optional author display name or email to filter by

        Returns:
            List of worklog entries matching the criteria
        """
        from datetime import datetime, timezone

        try:
            # Parse since_date to timestamp in milliseconds
            if "T" in since_date:
                since_dt = datetime.fromisoformat(since_date.replace("Z", "+00:00"))
            else:
                since_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
            since_timestamp_ms = int(since_dt.timestamp() * 1000)

            # Parse until_date if provided
            until_timestamp_ms = None
            if until_date:
                if "T" in until_date:
                    until_dt = datetime.fromisoformat(until_date.replace("Z", "+00:00"))
                else:
                    # End of day for date-only input
                    until_dt = datetime.strptime(until_date, "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59, tzinfo=timezone.utc
                    )
                until_timestamp_ms = int(until_dt.timestamp() * 1000)

            # Step 1: Get all worklog IDs updated since the start date
            all_worklog_ids = []
            result = self.get_worklogs_updated_since(since_timestamp_ms)

            for entry in result.get("values", []):
                worklog_id = entry.get("worklogId")
                updated_time = entry.get("updatedTime")

                # Filter by until_date if specified
                if until_timestamp_ms and updated_time:
                    if updated_time > until_timestamp_ms:
                        continue

                if worklog_id:
                    all_worklog_ids.append(worklog_id)

            # Handle pagination if there are more results
            while not result.get("lastPage", True) and result.get("nextPage"):
                # The nextPage URL contains the since parameter for the next batch
                next_since = result.get("until")
                if next_since:
                    result = self.get_worklogs_updated_since(int(next_since))
                    for entry in result.get("values", []):
                        worklog_id = entry.get("worklogId")
                        updated_time = entry.get("updatedTime")
                        if until_timestamp_ms and updated_time:
                            if updated_time > until_timestamp_ms:
                                continue
                        if worklog_id:
                            all_worklog_ids.append(worklog_id)
                else:
                    break

            if not all_worklog_ids:
                return []

            # Step 2: Fetch full worklog details in batches (API limit is 1000 IDs per request)
            all_worklogs = []
            batch_size = 1000
            for i in range(0, len(all_worklog_ids), batch_size):
                batch_ids = all_worklog_ids[i : i + batch_size]
                batch_worklogs = self.get_worklogs_by_ids(batch_ids)
                all_worklogs.extend(batch_worklogs)

            # Step 3: Filter by author if specified
            if author_filter:
                author_lower = author_filter.lower()
                all_worklogs = [
                    w
                    for w in all_worklogs
                    if author_lower in w.get("author", "").lower()
                ]

            # Sort by started date descending (most recent first)
            all_worklogs.sort(key=lambda w: w.get("started", ""), reverse=True)

            return all_worklogs

        except Exception as e:  # noqa: BLE001 - Intentional re-raise with context
            logger.error(f"Error getting worklogs by date range: {e}")
            msg = f"Error getting worklogs by date range: {e}"
            raise Exception(msg) from e
