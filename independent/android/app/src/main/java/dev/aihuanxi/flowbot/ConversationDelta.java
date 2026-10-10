package dev.aihuanxi.flowbot;

import java.util.ArrayList;
import java.util.List;

/** New rows after the shared tail; initial snapshots and disconnected windows are baselines. */
final class ConversationDelta {
    private List<String> previous;
    void reset() { previous = null; }
    int update(List<String> current) {
        int start = current.size();
        if (previous != null) {
            if (previous.isEmpty()) start = 0;
            else for (int size = Math.min(previous.size(), current.size()); size > 0; size--) {
                if (previous.subList(previous.size()-size, previous.size()).equals(current.subList(0, size))) {
                    start = size; break;
                }
            }
        }
        previous = new ArrayList<>(current);
        return start;
    }
}
