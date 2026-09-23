import pytest
from unittest.mock import MagicMock, patch
from app.minutes_generator import MeetingMinutesGenerator, MeetingSegment

def test_retry_on_timed_out_error():
    generator = MeetingMinutesGenerator(api_key="fake")
    
    # Mock the client's chat.complete to fail with "timed out" twice, then succeed
    mock_complete = MagicMock()
    
    class FakeResponse:
        class Choice:
            class Message:
                content = "success content"
            message = Message()
        choices = [Choice()]
    
    mock_complete.side_effect = [
        Exception("The read operation timed out"),
        Exception("The read operation timed out"),
        FakeResponse()
    ]
    
    generator.client.chat.complete = mock_complete
    
    # Fast-forward the sleep so tests run quickly
    with patch("time.sleep", return_value=None):
        result = generator._api_call_with_retry([{"role": "user", "content": "hello"}])
        
    assert result == "success content"
    assert mock_complete.call_count == 3

def test_actual_attempts_reported_in_error():
    generator = MeetingMinutesGenerator(api_key="fake")
    
    # Mock to fail with a non-retryable error
    mock_complete = MagicMock()
    mock_complete.side_effect = Exception("Some completely unknown fatal error")
    generator.client.chat.complete = mock_complete
    
    with pytest.raises(RuntimeError) as exc_info:
        generator._api_call_with_retry([{"role": "user", "content": "hello"}])
        
    # It should only attempt once because it's a non-retryable error
    assert mock_complete.call_count == 1
    # The error message should accurately reflect that it failed after 1 attempt, not 5
    assert "after 1 attempts" in str(exc_info.value)

@patch("app.minutes_generator.Mistral")
def test_mistral_timeout_config(mock_mistral_class):
    # Ensure that we instantiate Mistral with a higher timeout_ms
    generator = MeetingMinutesGenerator(api_key="fake", timeout_ms=300000)
    mock_mistral_class.assert_called_with(api_key="fake", timeout_ms=300000)

