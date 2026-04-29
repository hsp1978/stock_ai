#!/usr/bin/env python3
"""
API Import Test - Verify all imports work correctly for API service
"""

import sys
import json

def test_imports():
    """Test all critical imports for API service"""

    results = []

    # Test 1: MultiAgentOrchestrator
    try:
        from stock_analyzer.multi_agent import MultiAgentOrchestrator
        orchestrator = MultiAgentOrchestrator()
        results.append({"module": "multi_agent.MultiAgentOrchestrator", "status": "✅ Success"})
    except Exception as e:
        results.append({"module": "multi_agent.MultiAgentOrchestrator", "status": f"❌ Failed: {str(e)}"})

    # Test 2: Ticker Validator
    try:
        from stock_analyzer.ticker_validator import validate_ticker, get_market_info
        test_ticker = validate_ticker("0126Z0.KS")
        results.append({"module": "ticker_validator", "status": "✅ Success"})
    except Exception as e:
        results.append({"module": "ticker_validator", "status": f"❌ Failed: {str(e)}"})

    # Test 3: Ticker Verifier
    try:
        from stock_analyzer.ticker_verifier import verify_and_validate
        # Test with a known good ticker
        test_result = verify_and_validate("005930.KS")
        if test_result['exists']:
            results.append({"module": "ticker_verifier", "status": "✅ Success"})
        else:
            results.append({"module": "ticker_verifier", "status": "⚠️ Import OK but verification failed"})
    except Exception as e:
        results.append({"module": "ticker_verifier", "status": f"❌ Failed: {str(e)}"})

    # Test 4: Enhanced Decision Maker
    try:
        from stock_analyzer.enhanced_decision_maker import EnhancedDecisionMaker
        dm = EnhancedDecisionMaker()
        results.append({"module": "enhanced_decision_maker", "status": "✅ Success"})
    except Exception as e:
        results.append({"module": "enhanced_decision_maker", "status": f"❌ Failed: {str(e)}"})

    # Test 5: ML Pipeline Fix
    try:
        from stock_analyzer.ml_pipeline_fix import enhanced_ml_ensemble
        results.append({"module": "ml_pipeline_fix", "status": "✅ Success"})
    except Exception as e:
        results.append({"module": "ml_pipeline_fix", "status": f"⚠️ Not found (optional module)"})

    # Test 6: Korean Stock Verifier FDR
    try:
        from stock_analyzer.korean_stock_verifier_fdr import verify_korean_stock_fdr
        results.append({"module": "korean_stock_verifier_fdr", "status": "✅ Success"})
    except Exception as e:
        results.append({"module": "korean_stock_verifier_fdr", "status": f"❌ Failed: {str(e)}"})

    # Test 7: Dual Node Config
    try:
        from stock_analyzer.dual_node_config import get_llm_config
        results.append({"module": "dual_node_config", "status": "✅ Success"})
    except Exception as e:
        results.append({"module": "dual_node_config", "status": f"⚠️ Not found (optional for single node)"})

    return results


def test_fake_ticker_rejection():
    """Test that fake tickers are properly rejected"""

    from stock_analyzer.multi_agent import MultiAgentOrchestrator

    orchestrator = MultiAgentOrchestrator()

    # Test with a clearly fake ticker
    result = orchestrator.analyze("FAKE999.KS")

    if result.get('error'):
        return {
            "test": "Fake ticker rejection",
            "status": "✅ Success - properly rejected",
            "error_msg": result['error']
        }
    else:
        return {
            "test": "Fake ticker rejection",
            "status": "❌ Failed - should have rejected fake ticker",
            "result": result
        }


if __name__ == "__main__":
    print("="*60)
    print("API Service Import Test")
    print("="*60)

    # Test imports
    print("\n1. Testing module imports...")
    import_results = test_imports()

    success_count = sum(1 for r in import_results if "✅" in r['status'])
    fail_count = sum(1 for r in import_results if "❌" in r['status'])
    warning_count = sum(1 for r in import_results if "⚠️" in r['status'])

    print("\nImport Results:")
    for result in import_results:
        print(f"  {result['module']}: {result['status']}")

    print(f"\n  Summary: {success_count} success, {fail_count} failed, {warning_count} warnings")

    # Test fake ticker rejection
    if success_count >= 4:  # At least core modules working
        print("\n2. Testing fake ticker rejection...")
        rejection_result = test_fake_ticker_rejection()
        print(f"  {rejection_result['test']}: {rejection_result['status']}")
        if 'error_msg' in rejection_result:
            print(f"    Error message: {rejection_result['error_msg']}")

    # Overall verdict
    print("\n" + "="*60)
    if fail_count == 0:
        print("✅ API SERVICE READY - All imports working correctly")
    elif fail_count <= 2:
        print("⚠️ API SERVICE PARTIALLY READY - Some optional modules missing")
    else:
        print("❌ API SERVICE NOT READY - Critical import failures detected")
    print("="*60)