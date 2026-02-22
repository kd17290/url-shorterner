#!/usr/bin/env python3
"""
CI/CD Monitor Script
Monitors GitHub Actions CI/CD pipeline status and provides alerts.
"""

import sys
import time
from datetime import datetime

import requests


def get_ci_status():
    """Get current CI/CD status from GitHub API"""
    try:
        # Get latest workflow runs
        response = requests.get(
            "https://api.github.com/repos/kd17290/url-shorterner/actions/runs?per_page=5",
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        response.raise_for_status()
        data = response.json()

        if "workflow_runs" not in data:
            print("❌ Error: Unexpected API response format")
            return None

        runs = data["workflow_runs"]
        if not runs:
            print("📭 No CI/CD runs found")
            return None

        print(f"🔍 Latest CI/CD Runs (as of {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}):")
        print("=" * 60)

        for i, run in enumerate(runs[:5], 1):
            name = run.get("name", "Unknown")
            status = run.get("status", "Unknown")
            conclusion = run.get("conclusion", "pending")
            created_at = run.get("created_at", "Unknown")
            html_url = run.get("html_url", "")

            # Status indicators
            status_emoji = (
                "🔄"
                if status == "in_progress"
                else "⏸️" if status == "queued" else "✅" if conclusion == "success" else "❌"
            )
            conclusion_emoji = "✅" if conclusion == "success" else "❌" if conclusion == "failure" else "⏸️"

            print(f"{i}. {name}")
            print(f"   Status: {status_emoji} {status}")
            print(f"   Result: {conclusion_emoji} {conclusion}")
            print(f"   Time: {created_at}")
            print(f"   URL: {html_url}")
            print()

        # Summary
        successful = sum(1 for run in runs if run.get("conclusion") == "success")
        failed = sum(1 for run in runs if run.get("conclusion") == "failure")
        pending = sum(1 for run in runs if run.get("status") in ["in_progress", "queued"])

        print(f"📊 Summary: {successful} ✅ Success, {failed} ❌ Failed, {pending} 🔄 Pending")

        # Alert if there are failures
        if failed > 0:
            print(f"\n🚨 ALERT: {failed} CI/CD run(s) failed!")
            print("🔧 Check the failed runs above for details.")
            return False

        if pending > 0:
            print(f"\n⏳ INFO: {pending} CI/CD run(s) in progress...")
            return None

        print("\n✅ All CI/CD runs passed!")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def monitor_ci(interval_minutes=2, max_checks=30):
    """Monitor CI/CD status continuously"""
    print(f"👁️ Starting CI/CD monitoring (checking every {interval_minutes} minutes)")
    print(f"⏰ Maximum monitoring time: {max_checks * interval_minutes} minutes")
    print()

    check_count = 0
    while check_count < max_checks:
        check_count += 1
        print(f"\n--- Check #{check_count} at {datetime.now().strftime('%H:%M:%S')} ---")

        status = get_ci_status()

        if status is False:  # Failed
            print("💥 CI/CD failures detected! Check the logs above.")
            break
        elif status is True:  # Success
            print("🎉 All CI/CD checks passed!")
            break
        else:  # In progress
            print(f"⏳ Waiting {interval_minutes} minutes...")
            time.sleep(interval_minutes * 60)

    print(f"\n🏁 Monitoring completed after {check_count} checks")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--monitor":
        # Continuous monitoring mode
        monitor_ci()
    else:
        # Single check mode
        get_ci_status()
