package dev.aihuanxi.flowbot;

public class NotificationTextTest {
    public static void main(String[] args) {
        assert NotificationText.body("[2条]FlowBot测试", "FlowBot测试").equals("FlowBot测试");
        assert NotificationText.body("[12条]a+b[1]", "a+b[1]").equals("a+b[1]");
        assert NotificationText.body("FlowBot测试", "FlowBot测试").equals("FlowBot测试");
        assert NotificationText.body("[2条]FlowBot测试", "[2条]FlowBot测试").equals("[2条]FlowBot测试");
        assert NotificationText.body("[3条][2条]FlowBot测试", "[2条]FlowBot测试").equals("[2条]FlowBot测试");
        assert NotificationText.body("[2条]FlowBot测试", "其他内容").equals("[2条]FlowBot测试");
        assert NotificationText.body("[2条]FlowBot测试", null).equals("[2条]FlowBot测试");
        assert NotificationText.body(null, "FlowBot测试").isEmpty();
        System.out.println("Notification text calibration: 8 assertions passed");
    }
}
