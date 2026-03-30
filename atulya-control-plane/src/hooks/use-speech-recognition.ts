import { useCallback, useEffect, useRef, useState } from "react";

export interface SpeechRecognitionState {
  isSupported: boolean;
  isListening: boolean;
  interimTranscript: string;
  elapsedSeconds: number;
  error: string | null;
}

export interface UseSpeechRecognitionOptions {
  lang?: string;
  onFinalTranscript: (text: string) => void;
}

export interface UseSpeechRecognitionReturn extends SpeechRecognitionState {
  start: () => void;
  stop: () => void;
  toggle: () => void;
}

const SILENT_ERRORS = new Set(["aborted", "no-speech"]);

const getRecognitionConstructor = (): typeof SpeechRecognition | null => {
  if (typeof window === "undefined") {
    return null;
  }

  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
};

const toSpeechErrorMessage = (errorCode: string): string => {
  switch (errorCode) {
    case "audio-capture":
      return "No microphone was detected";
    case "network":
      return "Network error while processing speech";
    case "not-allowed":
    case "service-not-allowed":
      return "Microphone access was denied";
    case "language-not-supported":
      return "The selected language is not supported";
    default:
      return errorCode.replace(/-/g, " ");
  }
};

export function useSpeechRecognition({
  lang = "en-US",
  onFinalTranscript,
}: UseSpeechRecognitionOptions): UseSpeechRecognitionReturn {
  const [isSupported, setIsSupported] = useState(() => Boolean(getRecognitionConstructor()));
  const [isListening, setIsListening] = useState(false);
  const [interimTranscript, setInterimTranscript] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const sessionStartedAtRef = useRef<number | null>(null);
  const shouldRestartRef = useRef(false);
  const onFinalTranscriptRef = useRef(onFinalTranscript);

  useEffect(() => {
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onFinalTranscript]);

  const stopElapsedTimer = useCallback((resetSession: boolean) => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (resetSession) {
      sessionStartedAtRef.current = null;
      setElapsedSeconds(0);
    }
  }, []);

  const startElapsedTimer = useCallback(() => {
    if (sessionStartedAtRef.current === null) {
      sessionStartedAtRef.current = Date.now();
      setElapsedSeconds(0);
    }

    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    intervalRef.current = setInterval(() => {
      if (sessionStartedAtRef.current === null) {
        return;
      }
      const elapsed = Math.floor((Date.now() - sessionStartedAtRef.current) / 1000);
      setElapsedSeconds(elapsed);
    }, 1000);
  }, []);

  useEffect(() => {
    const RecognitionCtor = getRecognitionConstructor();
    setIsSupported(Boolean(RecognitionCtor));

    if (!RecognitionCtor) {
      return;
    }

    const recognition = new RecognitionCtor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = lang;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      setError(null);
      setIsListening(true);
      startElapsedTimer();
    };

    recognition.onresult = (event) => {
      let finalTranscript = "";
      let interim = "";

      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript?.trim();
        if (!transcript) {
          continue;
        }

        if (result.isFinal) {
          finalTranscript = finalTranscript ? `${finalTranscript} ${transcript}` : transcript;
        } else {
          interim = interim ? `${interim} ${transcript}` : transcript;
        }
      }

      setInterimTranscript(interim);

      if (finalTranscript) {
        setInterimTranscript("");
        onFinalTranscriptRef.current(finalTranscript);
      }
    };

    recognition.onerror = (event) => {
      if (!SILENT_ERRORS.has(event.error)) {
        setError(toSpeechErrorMessage(event.error));
      }

      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        shouldRestartRef.current = false;
      }
    };

    recognition.onend = () => {
      setIsListening(false);
      setInterimTranscript("");
      stopElapsedTimer(!shouldRestartRef.current);

      if (!shouldRestartRef.current) {
        return;
      }

      try {
        recognition.start();
      } catch {
        shouldRestartRef.current = false;
        stopElapsedTimer(true);
      }
    };

    recognitionRef.current = recognition;

    return () => {
      shouldRestartRef.current = false;
      stopElapsedTimer(true);
      recognition.onstart = null;
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      if (recognitionRef.current === recognition) {
        recognitionRef.current = null;
      }
      try {
        recognition.abort();
      } catch {
        // Ignore shutdown errors from browsers that already stopped the session.
      }
    };
  }, [lang, startElapsedTimer, stopElapsedTimer]);

  const start = useCallback(() => {
    const recognition = recognitionRef.current;
    if (!recognition) {
      setError("Speech recognition is not supported in this browser");
      return;
    }

    shouldRestartRef.current = true;
    sessionStartedAtRef.current = null;
    setElapsedSeconds(0);
    setError(null);

    try {
      recognition.lang = lang;
      recognition.start();
    } catch (error) {
      if (error instanceof DOMException && error.name === "InvalidStateError") {
        return;
      }
      shouldRestartRef.current = false;
      setError("Unable to start speech recognition");
    }
  }, [lang]);

  const stop = useCallback(() => {
    shouldRestartRef.current = false;
    setIsListening(false);
    setInterimTranscript("");
    stopElapsedTimer(true);

    try {
      recognitionRef.current?.stop();
    } catch {
      // Ignore stop errors when the browser has already ended the session.
    }
  }, [stopElapsedTimer]);

  const toggle = useCallback(() => {
    if (isListening) {
      stop();
      return;
    }
    start();
  }, [isListening, start, stop]);

  return {
    isSupported,
    isListening,
    interimTranscript,
    elapsedSeconds,
    error,
    start,
    stop,
    toggle,
  };
}
