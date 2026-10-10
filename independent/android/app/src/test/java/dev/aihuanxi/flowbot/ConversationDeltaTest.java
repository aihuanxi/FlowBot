package dev.aihuanxi.flowbot;
import java.util.Arrays;
import java.util.Collections;
final class ConversationDeltaTest {
    public static void main(String[] args) {
        ConversationDelta d = new ConversationDelta();
        assert d.update(Arrays.asList("3:I:旧消息", "4:O:自己发的")) == 2;
        assert d.update(Arrays.asList("3:I:旧消息", "4:O:自己发的")) == 2;
        assert d.update(Arrays.asList("4:O:自己发的", "5:I:新消息", "6:I:新消息")) == 1;
        assert d.update(Arrays.asList("5:I:新消息", "6:I:新消息", "7:O:回复")) == 2;
        assert d.update(Arrays.asList("0:I:历史", "1:I:历史")) == 2;
        d.reset(); assert d.update(Arrays.asList("5:I:新消息", "6:I:新消息")) == 2;
        d.reset(); assert d.update(Collections.emptyList()) == 0;
        assert d.update(Arrays.asList("0:I:首次来信")) == 0;
        System.out.println("ConversationDelta: 8 assertions passed");
    }
}
